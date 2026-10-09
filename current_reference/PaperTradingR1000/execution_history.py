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


def load_broker_execution_history(
    limit: int = 20, path: Path = cfg.EXECUTION_HISTORY_DB
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read confirmed Flex fills and API fills still awaiting Flex confirmation.

    This is read-only; the legacy executions table is a separate bot audit store.
    """
    limit = int(limit)
    if limit < 1:
        raise ValueError("The number of executions must be positive.")
    if not path.exists():
        return [], {"total_rows": 0, "source": "broker_execution_ledger"}
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        confirmed_count = conn.execute(
            "SELECT COUNT(*) FROM flex_executions"
        ).fetchone()[0]
        pending_where = """first_seen_source='IBKR_API'
            AND flex_confirmed_at_utc IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM flex_executions f WHERE f.ib_exec_id=n.exec_id
            )"""
        pending_count = conn.execute(
            f"SELECT COUNT(*) FROM execution_notifications n WHERE {pending_where}"
        ).fetchone()[0]
        confirmed = conn.execute(
            """SELECT date_time, symbol, side, quantity, price, ib_exec_id
               FROM flex_executions
               ORDER BY trade_date DESC, date_time DESC, id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        pending = conn.execute(
            f"""SELECT execution_time, symbol, side, quantity, price, exec_id
                FROM execution_notifications n WHERE {pending_where}
                ORDER BY execution_time DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    rows = [
        dict(zip(("time", "symbol", "side", "quantity", "price", "exec_id"), values),
             source="FLEX confirmed")
        for values in confirmed
    ]
    rows.extend(
        dict(zip(("time", "symbol", "side", "quantity", "price", "exec_id"), values),
             source="IBKR API (awaiting Flex)")
        for values in pending
    )
    rows.sort(
        key=lambda row: "".join(ch for ch in str(row["time"] or "") if ch.isdigit())[:14],
        reverse=True,
    )
    return rows[:limit], {
        "total_rows": confirmed_count + pending_count,
        "confirmed_rows": confirmed_count,
        "pending_rows": pending_count,
        "source": "broker_execution_ledger",
    }


def ingest_executions(rows: Iterable[dict[str, Any]]) -> int:
    with connect() as conn:
        count = 0
        for row in rows:
            record_execution(conn, row)
            count += 1
    return count
