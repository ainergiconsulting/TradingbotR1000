"""Reporting for R1000 scan, order-plan, and reconciliation evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import config as cfg
from monitoring_core import read_json
from monitoring_io import utc_timestamp


def latest_scan_report() -> dict[str, Any]:
    return read_json(cfg.SCAN_REPORT_FILE)


def write_scan_csv(scan: dict[str, Any], path: Path | None = None) -> Path:
    target = path or (cfg.REPORTS_DIR / "daily_scan_report.csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "symbol",
        "signal_day_close",
        "moving_average",
        "lower_bollinger_band",
        "ranking_return",
        "trend_condition",
        "pullback_condition",
        "is_candidate",
        "selected",
    ]
    selected = {row["symbol"] for row in scan.get("selected_candidates", [])}
    rows = []
    for row in scan.get("evaluated_candidates", []):
        item = {field: row.get(field, "") for field in fields}
        item["selected"] = row.get("symbol") in selected
        rows.append(item)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return target


def build_summary(scan: dict[str, Any] | None = None) -> dict[str, Any]:
    scan = scan or latest_scan_report()
    return {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "scan_timestamp_utc": scan.get("timestamp_utc"),
        "evaluated": len(scan.get("evaluated_candidates", [])),
        "selected": len(scan.get("selected_candidates", [])),
        "skipped": len(scan.get("skipped_candidates", [])),
        "orders": len(scan.get("order_plans", [])),
        "exit_signals": len(scan.get("exit_signals", [])),
        "available_slots": scan.get("available_slots"),
        "net_liquidation_value": scan.get("net_liquidation_value"),
        "investable_capital": scan.get("investable_capital"),
        "liquidity_reserve": scan.get("liquidity_reserve"),
        "ranking_applied": scan.get("ranking_applied"),
        "execute_orders": scan.get("execute_orders"),
    }


def write_summary_report(scan: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = build_summary(scan)
    cfg.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.REPORTS_DIR / "summary_report.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    if scan:
        write_scan_csv(scan)
    return summary
