"""Excel-feed generation for standalone Flex analytics."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import EXCEL_FEED_DIR


@dataclass(frozen=True)
class FeedSchema:
    name: str
    fields: tuple[str, ...]


FEED_SCHEMAS = {
    "daily_nav": FeedSchema("daily_nav", ("report_date", "starting_nav", "ending_nav", "realized", "change_unrealized", "mtm", "commissions")),
    "cumulative_return": FeedSchema("cumulative_return", ("report_date", "cumulative_pnl", "cumulative_return_pct")),
    "pnl_by_symbol": FeedSchema("pnl_by_symbol", ("report_date", "symbol", "conid", "net_pnl_base", "commissions_base", "pnl_pct")),
    "commissions": FeedSchema("commissions", ("trade_date", "symbol", "commission_base")),
    "executions": FeedSchema("executions", ("trade_date", "symbol", "conid", "buy_sell", "quantity", "trade_price", "commission_base")),
}


class ExcelFeedError(RuntimeError):
    pass


def _rows(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query).fetchall()]


def build_excel_feed_data(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    daily_nav = _rows(conn, "SELECT * FROM daily_nav ORDER BY report_date")
    cumulative = []
    first_nav = daily_nav[0]["starting_nav"] if daily_nav else 0
    for row in daily_nav:
        pnl = (row.get("ending_nav") or 0) - (first_nav or 0)
        cumulative.append(
            {
                "report_date": row["report_date"],
                "cumulative_pnl": pnl,
                "cumulative_return_pct": (pnl / first_nav) if first_nav else 0,
            }
        )
    return {
        "daily_nav": daily_nav,
        "cumulative_return": cumulative,
        "pnl_by_symbol": _rows(conn, "SELECT * FROM symbol_pnl ORDER BY report_date, symbol, conid"),
        "commissions": _rows(conn, "SELECT trade_date, symbol, commission_base FROM executions ORDER BY trade_date, symbol"),
        "executions": _rows(conn, "SELECT * FROM executions ORDER BY trade_date, symbol"),
    }


def export_excel_feeds(conn: sqlite3.Connection, output_dir: Path = EXCEL_FEED_DIR) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = build_excel_feed_data(conn)
    paths = []
    for name, rows in data.items():
        schema = FEED_SCHEMAS[name]
        path = output_dir / f"{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=schema.fields)
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in schema.fields} for row in rows)
        paths.append(path)
    return paths


def schema_summary() -> dict[str, tuple[str, ...]]:
    return {name: schema.fields for name, schema in FEED_SCHEMAS.items()}
