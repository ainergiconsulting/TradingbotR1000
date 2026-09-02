"""Incremental Russell 1000 daily-bar refresh from IBKR.

The refresher is fail-closed: it writes a status file and returns non-zero if
any required symbol cannot be brought to the latest completed IBKR session.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import config as cfg
from ibkr_utils import connect, stock_contract
from monitoring_io import atomic_write_json, utc_timestamp
from trading_engine import load_universe_symbol_records, _resolve_project_path
from config_loader import load_universe_config

STATUS_FILE = cfg.STATE_DIR / "ibkr_market_data_refresh.json"
DEFAULT_DURATION = "20 D"
FIELDS = ["ticker", "name", "con_id", "local_symbol", "date", "open", "high", "low", "close", "volume", "bar_count", "average"]


def _bar_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value or "").strip().replace("-", "")
    return text[:8]


def _num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return ""
    if number.is_integer():
        return str(int(number))
    return format(number, ".10g")


def _read_rows(path: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    if not path.exists():
        return [], {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    meta = rows[0] if rows else {}
    return rows, meta


def _write_rows_atomic(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_name, path)
        os.chmod(path, 0o644)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _request_bars(ib: Any, symbol: str, duration: str) -> tuple[Any, list[Any]]:
    contract = stock_contract(symbol)
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        raise RuntimeError("contract_not_qualified")
    contract = qualified[0]
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting="1 day",
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
        keepUpToDate=False,
    )
    return contract, list(bars)


def _latest_completed_ibkr_date(ib: Any) -> str:
    _contract, bars = _request_bars(ib, "SPY", "10 D")
    if not bars:
        raise RuntimeError("reference_market_data_unavailable")
    # Before the regular close, today's daily bar is incomplete and must not be
    # used. After 16:15 ET, today's completed bar is eligible. On the normal
    # 09:28 ET strategy run this therefore resolves to the previous completed
    # IBKR session, including holiday/weekend handling from IBKR itself.
    from zoneinfo import ZoneInfo
    now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    today_et = now_et.strftime("%Y%m%d")
    allow_today = (now_et.hour, now_et.minute) >= (16, 15)
    completed = [
        _bar_date(bar.date)
        for bar in bars
        if _bar_date(bar.date) < today_et or (allow_today and _bar_date(bar.date) == today_et)
    ]
    if not completed:
        raise RuntimeError("reference_completed_session_unavailable")
    return max(completed)


def refresh(*, limit: int | None = None, duration: str = DEFAULT_DURATION, pause: float = 0.20) -> dict[str, Any]:
    cfg.ensure_runtime_dirs()
    universe_config = load_universe_config()
    universe_path = _resolve_project_path(universe_config["source_path"])
    daily_bars_dir = _resolve_project_path(universe_config["daily_bars_dir"])
    symbols = list(load_universe_symbol_records(universe_path, universe_config.get("symbol_column", "symbol"))["symbols"])
    if limit is not None:
        symbols = symbols[: max(0, int(limit))]

    started = utc_timestamp()
    failures: list[dict[str, str]] = []
    updated = 0
    already_current = 0
    rows_added = 0
    ib = connect(client_id=cfg.MARKET_DATA_CLIENT_ID, readonly=True)
    try:
        expected_date = _latest_completed_ibkr_date(ib)
        for index, symbol in enumerate(symbols, start=1):
            path = daily_bars_dir / f"{symbol}.csv"
            requested_data = False
            try:
                existing, meta = _read_rows(path)
                existing_by_date = {str(row.get("date") or ""): row for row in existing if row.get("date")}
                old_latest = max(existing_by_date, default="")
                if old_latest >= expected_date:
                    already_current += 1
                    continue
                requested_data = True
                contract, bars = _request_bars(ib, symbol, duration)
                additions = 0
                for bar in bars:
                    d = _bar_date(bar.date)
                    if not d or d > expected_date or d in existing_by_date:
                        continue
                    existing_by_date[d] = {
                        "ticker": symbol,
                        "name": str(meta.get("name") or symbol),
                        "con_id": str(getattr(contract, "conId", "") or meta.get("con_id") or ""),
                        "local_symbol": str(getattr(contract, "localSymbol", "") or meta.get("local_symbol") or symbol),
                        "date": d,
                        "open": _num(bar.open),
                        "high": _num(bar.high),
                        "low": _num(bar.low),
                        "close": _num(bar.close),
                        "volume": _num(bar.volume),
                        "bar_count": _num(getattr(bar, "barCount", "")),
                        "average": _num(getattr(bar, "average", "")),
                    }
                    additions += 1
                final_rows = [existing_by_date[d] for d in sorted(existing_by_date)]
                final_latest = max(existing_by_date, default="")
                if final_latest != expected_date:
                    raise RuntimeError(f"latest_date_{final_latest or 'missing'}_expected_{expected_date}")
                if additions:
                    _write_rows_atomic(path, final_rows)
                    updated += 1
                    rows_added += additions
                else:
                    already_current += 1
            except Exception as exc:
                failures.append({"symbol": symbol, "error": f"{type(exc).__name__}:{exc}"})
            if requested_data and pause > 0 and index < len(symbols):
                ib.sleep(pause)
    finally:
        ib.disconnect()

    unresolved_contracts = [
        item for item in failures if "contract_not_qualified" in str(item.get("error") or "")
    ]
    only_unresolved_contracts = len(unresolved_contracts) == len(failures)
    degraded_acceptable = bool(failures) and only_unresolved_contracts and len(failures) <= 10
    status = (
        "OK"
        if not failures and len(symbols) > 0
        else "DEGRADED_ACCEPTABLE"
        if degraded_acceptable
        else "FAILED"
    )
    payload = {
        "bot": cfg.BOT_NAME,
        "source": "IBKR",
        "status": status,
        "started_at_utc": started,
        "completed_at_utc": utc_timestamp(),
        "expected_latest_completed_session": expected_date,
        "symbols_targeted": len(symbols),
        "symbols_updated": updated,
        "symbols_already_current": already_current,
        "rows_added": rows_added,
        "failure_count": len(failures),
        "failures": failures[:100],
        "acceptable_unresolved_symbols": [item["symbol"] for item in unresolved_contracts] if degraded_acceptable else [],
        "trading_may_proceed": status in {"OK", "DEGRADED_ACCEPTABLE"},
    }
    atomic_write_json(STATUS_FILE, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh TradingbotR1000 daily bars incrementally from IBKR")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--duration", default=DEFAULT_DURATION)
    parser.add_argument("--pause", type=float, default=0.20)
    args = parser.parse_args(argv)
    payload = refresh(limit=args.limit, duration=args.duration, pause=args.pause)
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] in {"OK", "DEGRADED_ACCEPTABLE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
