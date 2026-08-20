"""Durable trade and order-plan logging for TradingbotR1000."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import config as cfg
from logger_utils import log
from monitoring_io import utc_timestamp


TRADE_FIELDS = [
    "timestamp_utc",
    "symbol",
    "side",
    "quantity",
    "price",
    "reason",
    "strategy_version",
    "source",
]


def append_trade_record(record: dict[str, Any], path: Path = cfg.TRADE_LOG_FILE) -> None:
    cfg.ensure_runtime_dirs()
    payload = {field: record.get(field, "") for field in TRADE_FIELDS}
    payload["timestamp_utc"] = payload["timestamp_utc"] or utc_timestamp()
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADE_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(payload)
    log("trade record appended", extra={"symbol": payload["symbol"], "side": payload["side"]})


def replay_spooled_trade_records() -> int:
    if not cfg.TRADE_SPOOL_FILE.exists():
        return 0
    count = sum(1 for line in cfg.TRADE_SPOOL_FILE.read_text(encoding="utf-8").splitlines() if line.strip())
    log("trade spool replay requested", extra={"records": count})
    return count
