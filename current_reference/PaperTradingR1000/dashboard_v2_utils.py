"""Dashboard section helpers for TradingbotR1000."""

from __future__ import annotations

import config as cfg
from monitoring_core import collect_runtime_status, read_json


def get_dashboard_sections() -> list[dict[str, object]]:
    runtime = collect_runtime_status()
    return [
        {"title": "Runtime", "content": runtime},
        {"title": "Broker Snapshot", "content": read_json(cfg.BROKER_SNAPSHOT_FILE)},
        {"title": "Daily Scan", "content": read_json(cfg.SCAN_REPORT_FILE)},
        {"title": "Reconciliation", "content": read_json(cfg.RECONCILIATION_REPORT_FILE)},
    ]
