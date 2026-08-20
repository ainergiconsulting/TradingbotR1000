"""Execution-history helpers for TradingbotR1000 reports."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import config as cfg
from monitoring_io import utc_timestamp


SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL,
    price REAL,
    reason TEXT,
    source TEXT,
    raw_json TEXT
)
"""


def connect(path: Path = cfg.EXECUTION_HISTORY_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    return conn


def record_execution(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO executions(timestamp_utc, symbol, side, quantity, price, reason, source, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("timestamp_utc") or utc_timestamp(),
            str(row.get("symbol", "")).upper(),
            str(row.get("side", "")).upper(),
            float(row.get("quantity", 0) or 0),
            float(row.get("price", 0) or 0),
            str(row.get("reason", "") or ""),
            str(row.get("source", "") or ""),
            json.dumps(row, sort_keys=True, default=str),
        ),
    )
    conn.commit()


def load_latest_execution_history(limit: int = 20, path: Path = cfg.EXECUTION_HISTORY_DB) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT timestamp_utc, symbol, side, quantity, price, reason, source FROM executions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "timestamp_utc": row[0],
            "symbol": row[1],
            "side": row[2],
            "quantity": row[3],
            "price": row[4],
            "reason": row[5],
            "source": row[6],
        }
        for row in rows
    ]


def ingest_executions(rows: Iterable[dict[str, Any]]) -> int:
    with connect() as conn:
        count = 0
        for row in rows:
            record_execution(conn, row)
            count += 1
    return count
