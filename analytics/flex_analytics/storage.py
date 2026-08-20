"""SQLite storage for standalone Flex analytics."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Iterable

from .config import DEFAULT_DB_PATH, NORMALIZED_DIR
from .normalize import NormalizedReport, parse_report


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_nav(
  report_date TEXT PRIMARY KEY,
  starting_nav REAL,
  ending_nav REAL,
  realized REAL,
  change_unrealized REAL,
  mtm REAL,
  commissions REAL
);
CREATE TABLE IF NOT EXISTS executions(
  ib_exec_id TEXT PRIMARY KEY,
  trade_date TEXT,
  symbol TEXT,
  conid TEXT,
  buy_sell TEXT,
  quantity REAL,
  trade_price REAL,
  commission_base REAL
);
CREATE TABLE IF NOT EXISTS symbol_pnl(
  report_date TEXT,
  symbol TEXT,
  conid TEXT,
  net_pnl_base REAL,
  commissions_base REAL,
  pnl_pct REAL,
  PRIMARY KEY(report_date, symbol, conid)
);
CREATE TABLE IF NOT EXISTS refresh_log(
  refreshed_at TEXT,
  source_path TEXT,
  sha256 TEXT,
  status TEXT
);
"""


def connect(path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def ingest_report(conn: sqlite3.Connection, report: NormalizedReport) -> None:
    for row in report.nav:
        conn.execute(
            "INSERT OR REPLACE INTO daily_nav VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row.get("report_date"),
                row.get("starting_nav"),
                row.get("ending_nav"),
                row.get("realized"),
                row.get("change_unrealized"),
                row.get("mtm"),
                row.get("commissions"),
            ),
        )
    for row in report.executions:
        conn.execute(
            "INSERT OR REPLACE INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.get("ib_exec_id") or row.get("trade_id"),
                row.get("trade_date"),
                row.get("symbol"),
                row.get("conid"),
                row.get("buy_sell"),
                row.get("quantity"),
                row.get("trade_price"),
                row.get("commission_base"),
            ),
        )
    for row in report.symbol_pnl:
        conn.execute(
            "INSERT OR REPLACE INTO symbol_pnl VALUES (?, ?, ?, ?, ?, ?)",
            (
                row.get("report_date"),
                row.get("symbol"),
                row.get("conid"),
                row.get("net_pnl_base"),
                row.get("commissions_base"),
                row.get("pnl_pct"),
            ),
        )
    conn.commit()


def ingest_report_path(conn: sqlite3.Connection, path: Path) -> NormalizedReport:
    report = parse_report(path)
    ingest_report(conn, report)
    log_refresh(conn, str(path), report.sha256, "SUCCESS")
    return report


def ingest_new_raw_reports(conn: sqlite3.Connection, raw_dir: Path) -> int:
    count = 0
    for path in sorted(raw_dir.glob("*.xml")):
        ingest_report_path(conn, path)
        count += 1
    return count


def export_normalized_csv(conn: sqlite3.Connection, output_dir: Path = NORMALIZED_DIR) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for table in ("daily_nav", "executions", "symbol_pnl"):
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        headers = [item[0] for item in conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
        path = output_dir / f"{table}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
        paths.append(path)
    return paths


def log_refresh(conn: sqlite3.Connection, source_path: str, sha256: str, status: str) -> None:
    conn.execute(
        "INSERT INTO refresh_log VALUES (datetime('now'), ?, ?, ?)",
        (source_path, sha256, status),
    )
    conn.commit()


def already_successful_for_date(_conn: sqlite3.Connection, _report_date: str) -> bool:
    return False
