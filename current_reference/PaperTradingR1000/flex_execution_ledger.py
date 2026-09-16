"""Persistent IBKR Flex execution ledger for TradingbotR1000.

Imports Trade rows from IBKR Flex Trade Confirmation XML into SQLite.
The ledger is read-only with respect to IBKR and deduplicates fills by the
broker trade/transaction identifiers present in Flex.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
import xml.etree.ElementTree as ET

import config as cfg


DB_PATH = cfg.EXECUTION_HISTORY_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS flex_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    trade_id TEXT,
    transaction_id TEXT,
    ib_exec_id TEXT,
    ib_order_id TEXT,
    account_id TEXT,
    trade_date TEXT,
    date_time TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    proceeds REAL,
    commission REAL,
    commission_currency TEXT,
    realized_pnl REAL,
    order_type TEXT,
    open_close TEXT,
    asset_category TEXT,
    conid TEXT,
    source_file TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    imported_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_flex_exec_trade_date ON flex_executions(trade_date);
CREATE INDEX IF NOT EXISTS idx_flex_exec_symbol ON flex_executions(symbol);
CREATE TABLE IF NOT EXISTS execution_notifications (
    exec_id TEXT PRIMARY KEY,
    first_seen_source TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    quantity REAL,
    price REAL,
    observed_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    telegram_notified_at_utc TEXT,
    flex_confirmed_at_utc TEXT
);
"""


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _source_key(a: dict[str, str]) -> str:
    trade_id = str(a.get("tradeID") or "").strip()
    if trade_id:
        return f"trade:{trade_id}"
    transaction_id = str(a.get("transactionID") or "").strip()
    if transaction_id:
        return f"txn:{transaction_id}"
    return "fallback:" + "|".join([
        str(a.get("accountId") or ""), str(a.get("dateTime") or ""),
        str(a.get("symbol") or ""), str(a.get("buySell") or ""),
        str(a.get("quantity") or ""), str(a.get("tradePrice") or ""),
    ])


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    # Create base tables first, then migrate older ledgers in place.
    conn.execute("""CREATE TABLE IF NOT EXISTS flex_executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source_key TEXT NOT NULL UNIQUE,
        trade_id TEXT, transaction_id TEXT, account_id TEXT, trade_date TEXT,
        date_time TEXT, symbol TEXT NOT NULL, side TEXT NOT NULL,
        quantity REAL NOT NULL, price REAL NOT NULL, proceeds REAL,
        commission REAL, commission_currency TEXT, realized_pnl REAL,
        order_type TEXT, open_close TEXT, asset_category TEXT, conid TEXT,
        source_file TEXT NOT NULL, raw_json TEXT NOT NULL,
        imported_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(flex_executions)")}
    if "ib_exec_id" not in cols:
        conn.execute("ALTER TABLE flex_executions ADD COLUMN ib_exec_id TEXT")
    if "ib_order_id" not in cols:
        conn.execute("ALTER TABLE flex_executions ADD COLUMN ib_order_id TEXT")
    # Rebuild the early claim-only notification table if necessary. It was
    # never populated in production, so no delivered-notification state is lost.
    ncols = {row[1] for row in conn.execute("PRAGMA table_info(execution_notifications)")}
    if ncols and "first_seen_source" not in ncols:
        count = conn.execute("SELECT COUNT(*) FROM execution_notifications").fetchone()[0]
        if count:
            raise RuntimeError("legacy execution_notifications contains rows; manual migration required")
        conn.execute("DROP TABLE execution_notifications")
    conn.executescript(SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_flex_exec_ib_exec_id ON flex_executions(ib_exec_id)")
    conn.commit()
    return conn


def parse_trade_rows(xml_path: Path) -> list[dict]:
    root = ET.parse(xml_path).getroot()
    rows = []
    for element in root.findall(".//Trade"):
        a = {str(k): str(v) for k, v in element.attrib.items()}
        symbol = str(a.get("symbol") or "").upper().strip()
        side = str(a.get("buySell") or "").upper().strip()
        if not symbol or side not in {"BUY", "SELL"}:
            continue
        qty = abs(_f(a.get("quantity")))
        if qty <= 0:
            continue
        rows.append({
            "source_key": _source_key(a),
            "trade_id": a.get("tradeID", ""),
            "transaction_id": a.get("transactionID", ""),
            "ib_exec_id": a.get("ibExecID", ""),
            "ib_order_id": a.get("ibOrderID", ""),
            "account_id": a.get("accountId", ""),
            "trade_date": a.get("tradeDate", ""),
            "date_time": a.get("dateTime", ""),
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "price": _f(a.get("tradePrice")),
            "proceeds": _f(a.get("proceeds")),
            "commission": _f(a.get("ibCommission")),
            "commission_currency": a.get("currency", ""),
            "realized_pnl": _f(a.get("fifoPnlRealized")),
            "order_type": a.get("orderType", ""),
            "open_close": a.get("openCloseIndicator", ""),
            "asset_category": a.get("assetCategory", ""),
            "conid": a.get("conid", ""),
            "source_file": xml_path.name,
            "raw_json": json.dumps(a, sort_keys=True),
        })
    return rows


def import_flex_xml(xml_path: Path, path: Path = DB_PATH) -> dict:
    rows = parse_trade_rows(xml_path)
    inserted = 0
    duplicates = 0
    inserted_rows = []
    with connect(path) as conn:
        for r in rows:
            cur = conn.execute(
                """INSERT OR IGNORE INTO flex_executions(
                    source_key, trade_id, transaction_id, ib_exec_id, ib_order_id, account_id, trade_date,
                    date_time, symbol, side, quantity, price, proceeds, commission,
                    commission_currency, realized_pnl, order_type, open_close,
                    asset_category, conid, source_file, raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["source_key"], r["trade_id"], r["transaction_id"], r["ib_exec_id"], r["ib_order_id"], r["account_id"],
                 r["trade_date"], r["date_time"], r["symbol"], r["side"], r["quantity"],
                 r["price"], r["proceeds"], r["commission"], r["commission_currency"],
                 r["realized_pnl"], r["order_type"], r["open_close"], r["asset_category"],
                 r["conid"], r["source_file"], r["raw_json"]),
            )
            if cur.rowcount == 1:
                inserted += 1
                inserted_rows.append({k: v for k, v in r.items() if k not in {"account_id", "raw_json"}})
            else:
                duplicates += 1
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM flex_executions").fetchone()[0]
    return {"parsed": len(rows), "inserted": inserted, "duplicates": duplicates, "total": total, "inserted_rows": inserted_rows}


def observe_execution(exec_id: str, *, source: str, symbol: str = "", side: str = "", quantity: float = 0.0, price: float = 0.0, path: Path = DB_PATH) -> bool:
    """Persist broker evidence and return True while Telegram delivery is still due."""
    exec_id = str(exec_id or "").strip()
    if not exec_id:
        return False
    source = str(source or "UNKNOWN").upper()
    with connect(path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO execution_notifications
               (exec_id,first_seen_source,symbol,side,quantity,price)
               VALUES (?,?,?,?,?,?)""",
            (exec_id, source, symbol, side, _f(quantity), _f(price)),
        )
        if source == "FLEX":
            conn.execute(
                "UPDATE execution_notifications SET flex_confirmed_at_utc=COALESCE(flex_confirmed_at_utc,strftime('%Y-%m-%dT%H:%M:%SZ','now')) WHERE exec_id=?",
                (exec_id,),
            )
        row = conn.execute(
            "SELECT telegram_notified_at_utc FROM execution_notifications WHERE exec_id=?", (exec_id,)
        ).fetchone()
        conn.commit()
        return bool(row and not row[0])


def mark_execution_notified(exec_id: str, path: Path = DB_PATH) -> None:
    """Mark delivery only after the Telegram transport completed successfully."""
    exec_id = str(exec_id or "").strip()
    if not exec_id:
        return
    with connect(path) as conn:
        conn.execute(
            "UPDATE execution_notifications SET telegram_notified_at_utc=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE exec_id=?",
            (exec_id,),
        )
        conn.commit()


def claim_execution_notification(exec_id: str, *, source: str, symbol: str = "", side: str = "", quantity: float = 0.0, price: float = 0.0, path: Path = DB_PATH) -> bool:
    """Compatibility alias: records observation but does not mark Telegram delivered."""
    return observe_execution(exec_id, source=source, symbol=symbol, side=side, quantity=quantity, price=price, path=path)


def latest(limit: int = 20, path: Path = DB_PATH) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            """SELECT date_time, trade_date, symbol, side, quantity, price,
                      proceeds, commission, realized_pnl, order_type, open_close,
                      trade_id, transaction_id
               FROM flex_executions
               ORDER BY trade_date DESC, date_time DESC, id DESC LIMIT ?""",
            (int(limit),),
        ).fetchall()
    keys = ["date_time","trade_date","symbol","side","quantity","price","proceeds",
            "commission","realized_pnl","order_type","open_close","trade_id","transaction_id"]
    return [dict(zip(keys, row)) for row in rows]


def pnl_summary(path: Path = DB_PATH) -> dict:
    with connect(path) as conn:
        total, first_date, last_date = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl),0), MIN(trade_date), MAX(trade_date) FROM flex_executions"
        ).fetchone()
        per_symbol = [
            {"symbol": s, "realized_pnl": pnl}
            for s, pnl in conn.execute(
                """SELECT symbol, COALESCE(SUM(realized_pnl),0)
                   FROM flex_executions GROUP BY symbol ORDER BY symbol"""
            ).fetchall()
        ]
    return {
        "cumulative_realized_pnl": float(total or 0),
        "cumulative_since": first_date,
        "through": last_date,
        "per_symbol": per_symbol,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("xml", type=Path)
    p.add_argument("--summary", action="store_true")
    args = p.parse_args(argv)
    result = import_flex_xml(args.xml)
    print(json.dumps(result, indent=2))
    if args.summary:
        print(json.dumps(pnl_summary(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
