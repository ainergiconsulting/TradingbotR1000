"""Durable read-only history of strategy candidates."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import config as cfg

ADDITIONAL_CANDIDATE_LIMIT = 10
ET = ZoneInfo("America/New_York")


def _symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or "").strip().upper()


def _ranking_value(row: dict[str, Any]) -> float:
    try:
        return float(row.get("ranking_return"))
    except (TypeError, ValueError):
        return float("-inf")


def _ranked(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (-_ranking_value(row), _symbol(row), str(row.get("symbol") or "")))


def _trade_date_et(scan: dict[str, Any], scan_kind: str) -> str:
    explicit = str(scan.get("preview_trade_date_et") or "").strip()
    if scan_kind == "PREVIEW" and explicit:
        return explicit
    raw = str(scan.get("timestamp_utc") or scan.get("timestamp") or "").strip()
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(ET).date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).astimezone(ET).date().isoformat()


def build_candidate_snapshot(
    scan: dict[str, Any],
    *,
    scan_kind: str,
    execution_report: dict[str, Any] | None = None,
    additional_limit: int = ADDITIONAL_CANDIDATE_LIMIT,
) -> dict[str, Any]:
    kind = str(scan_kind or "").strip().upper()
    if kind not in {"PREVIEW", "REGULAR"}:
        raise ValueError("scan_kind must be PREVIEW or REGULAR")

    selected = [dict(row) for row in (scan.get("selected_candidates") or [])]
    skipped = [dict(row) for row in (scan.get("skipped_candidates") or [])]
    selected_symbols = {_symbol(row) for row in selected}
    additional = [row for row in _ranked(skipped) if _symbol(row) not in selected_symbols]
    additional = additional[: max(0, int(additional_limit))]

    all_ranked = _ranked(selected + skipped)
    rank_by_symbol = {_symbol(row): idx + 1 for idx, row in enumerate(all_ranked)}

    plans = {
        _symbol(row): row
        for row in (scan.get("order_plans") or [])
        if str(row.get("side") or "BUY").upper() == "BUY"
    }
    submitted = {
        _symbol(row): row
        for row in ((execution_report or {}).get("submitted_orders") or [])
        if str(row.get("side") or "BUY").upper() == "BUY"
    }
    signal_dates = scan.get("signal_dates") or {}

    rows: list[dict[str, Any]] = []
    for category, source_rows in (("PLANNED", selected), ("ADDITIONAL_CANDIDATE", additional)):
        for row in source_rows:
            sym = _symbol(row)
            plan = plans.get(sym) or {}
            sent = submitted.get(sym)
            try:
                close = float(row.get("signal_day_close"))
            except (TypeError, ValueError):
                close = None
            limit_price = plan.get("limit_price")
            if limit_price in (None, "") and close is not None:
                limit_price = round(close * 0.97, 2)
            rows.append({
                "symbol": sym,
                "category": category,
                "strategy_rank": rank_by_symbol.get(sym),
                "ranking_return": row.get("ranking_return"),
                "signal_day_close": close,
                "limit_price_97pct": limit_price,
                "signal_date": plan.get("signal_date") or signal_dates.get(sym) or "",
                "planned_quantity": plan.get("quantity") if category == "PLANNED" else None,
                "broker_submitted": bool(sent),
                "broker_status": (sent or {}).get("broker_status") if sent else None,
                "ibkr_order_id": (sent or {}).get("ibkr_order_id") if sent else None,
            })

    return {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scan_timestamp_utc": scan.get("timestamp_utc") or scan.get("timestamp"),
        "cycle_id": scan.get("cycle_id"),
        "scan_kind": kind,
        "trade_date_et": _trade_date_et(scan, kind),
        "strategy_version": scan.get("strategy_version"),
        "ranking_metric": "150_day_price_appreciation",
        "buy_limit_multiplier": 0.97,
        "planned_count": len(selected),
        "additional_count": len(additional),
        "broker_orders_transmitted": int((execution_report or {}).get("broker_orders_transmitted") or 0),
        "candidates": rows,
    }


def record_candidate_snapshot(
    scan: dict[str, Any],
    *,
    scan_kind: str,
    execution_report: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    target = Path(path or cfg.CANDIDATE_HISTORY_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_candidate_snapshot(scan, scan_kind=scan_kind, execution_report=execution_report)
    key = (snapshot.get("cycle_id"), snapshot.get("scan_kind"), snapshot.get("trade_date_et"))

    if target.exists():
        try:
            for line in target.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                existing = json.loads(line)
                existing_key = (existing.get("cycle_id"), existing.get("scan_kind"), existing.get("trade_date_et"))
                if existing_key == key:
                    return existing
        except (OSError, json.JSONDecodeError):
            pass

    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, separators=(",", ":"), sort_keys=True) + "\n")
    try:
        target.chmod(0o644)
    except OSError:
        pass
    return snapshot


def load_candidate_snapshots(path: Path | None = None) -> list[dict[str, Any]]:
    target = Path(path or cfg.CANDIDATE_HISTORY_FILE)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def recent_candidate_history(*, days: int = 15, path: Path | None = None) -> list[dict[str, Any]]:
    days = max(1, min(int(days), 90))
    cutoff = datetime.now(timezone.utc).astimezone(ET).date() - timedelta(days=days - 1)
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in load_candidate_snapshots(path):
        try:
            d = date.fromisoformat(str(row.get("trade_date_et") or ""))
        except ValueError:
            continue
        if d < cutoff:
            continue
        by_date.setdefault(d.isoformat(), []).append(row)

    result: list[dict[str, Any]] = []
    for trade_date in sorted(by_date, reverse=True):
        choices = by_date[trade_date]
        regular = [row for row in choices if str(row.get("scan_kind")).upper() == "REGULAR"]
        pool = regular or choices
        pool.sort(key=lambda row: str(row.get("recorded_at_utc") or ""), reverse=True)
        result.append(pool[0])
    return result
