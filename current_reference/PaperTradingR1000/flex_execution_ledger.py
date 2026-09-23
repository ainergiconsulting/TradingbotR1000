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
    source_kind TEXT NOT NULL DEFAULT 'FLEX',
    flex_confirmed INTEGER NOT NULL DEFAULT 1,
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
    flex_confirmed_at_utc TEXT,
    execution_time TEXT,
    ib_order_id TEXT,
    commission REAL,
    commission_currency TEXT,
    realized_pnl REAL,
    notification_status TEXT NOT NULL DEFAULT 'PENDING'
);
CREATE TABLE IF NOT EXISTS flex_coverage (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    coverage_from TEXT,
    coverage_through TEXT,
    generated_at TEXT,
    source_file TEXT,
    updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
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
    if "source_kind" not in cols:
        conn.execute("ALTER TABLE flex_executions ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'FLEX'")
    if "flex_confirmed" not in cols:
        conn.execute("ALTER TABLE flex_executions ADD COLUMN flex_confirmed INTEGER NOT NULL DEFAULT 1")
    conn.executescript(SCHEMA)
    ncols = {row[1] for row in conn.execute("PRAGMA table_info(execution_notifications)")}
    if "execution_time" not in ncols:
        conn.execute("ALTER TABLE execution_notifications ADD COLUMN execution_time TEXT")
    if "ib_order_id" not in ncols:
        conn.execute("ALTER TABLE execution_notifications ADD COLUMN ib_order_id TEXT")
    if "commission" not in ncols:
        conn.execute("ALTER TABLE execution_notifications ADD COLUMN commission REAL")
    if "commission_currency" not in ncols:
        conn.execute("ALTER TABLE execution_notifications ADD COLUMN commission_currency TEXT")
    if "realized_pnl" not in ncols:
        conn.execute("ALTER TABLE execution_notifications ADD COLUMN realized_pnl REAL")
    if "notification_status" not in ncols:
        conn.execute("ALTER TABLE execution_notifications ADD COLUMN notification_status TEXT NOT NULL DEFAULT 'PENDING'")
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


def observe_execution(exec_id: str, *, source: str, symbol: str = "", side: str = "", quantity: float = 0.0, price: float = 0.0, execution_time: str = "", ib_order_id: str = "", path: Path = DB_PATH) -> bool:
    """Persist broker execution evidence and return True while Telegram delivery is due."""
    exec_id = str(exec_id or "").strip()
    if not exec_id:
        return False
    source = str(source or "UNKNOWN").upper()
    with connect(path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO execution_notifications
               (exec_id,first_seen_source,symbol,side,quantity,price,execution_time)
               VALUES (?,?,?,?,?,?,?)""",
            (exec_id, source, symbol, side, _f(quantity), _f(price), str(execution_time or "")),
        )
        if ib_order_id:
            conn.execute("UPDATE execution_notifications SET ib_order_id=COALESCE(NULLIF(ib_order_id,''),?) WHERE exec_id=?", (str(ib_order_id), exec_id))
        conn.execute(
            """UPDATE execution_notifications SET
               symbol=COALESCE(NULLIF(?,''),symbol), side=COALESCE(NULLIF(?,''),side),
               quantity=CASE WHEN ?>0 THEN ? ELSE quantity END,
               price=CASE WHEN ?>0 THEN ? ELSE price END,
               execution_time=COALESCE(NULLIF(?,''),execution_time),
               ib_order_id=COALESCE(NULLIF(?,''),ib_order_id)
               WHERE exec_id=?""",
            (symbol, side, _f(quantity), _f(quantity), _f(price), _f(price), str(execution_time or ""), str(ib_order_id or ""), exec_id),
        )
        if source == "FLEX":
            conn.execute(
                "UPDATE execution_notifications SET flex_confirmed_at_utc=COALESCE(flex_confirmed_at_utc,strftime('%Y-%m-%dT%H:%M:%SZ','now')) WHERE exec_id=?",
                (exec_id,),
            )
        row = conn.execute("SELECT telegram_notified_at_utc FROM execution_notifications WHERE exec_id=?", (exec_id,)).fetchone()
        conn.commit()
        return bool(row and not row[0])


def record_commission_report(exec_id: str, commission: float | None, currency: str = "", realized_pnl: float | None = None, path: Path = DB_PATH) -> None:
    """Attach IBKR CommissionReport accounting fields to an observed execution."""
    exec_id = str(exec_id or "").strip()
    if not exec_id:
        return
    with connect(path) as conn:
        conn.execute(
            """UPDATE execution_notifications
               SET commission=?, commission_currency=?, realized_pnl=?
               WHERE exec_id=?""",
            (commission, str(currency or ""), realized_pnl, exec_id),
        )
        conn.commit()


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
                      trade_id, transaction_id, ib_exec_id, ib_order_id, source_kind, flex_confirmed
               FROM flex_executions
               ORDER BY trade_date DESC, date_time DESC, id DESC LIMIT ?""",
            (int(limit),),
        ).fetchall()
    keys = ["date_time","trade_date","symbol","side","quantity","price","proceeds",
            "commission","realized_pnl","order_type","open_close","trade_id","transaction_id",
            "ib_exec_id","ib_order_id","source_kind","flex_confirmed"]
    return [dict(zip(keys, row)) for row in rows]


def order_history(*, start_date: str | None = None, side: str = "ALL", symbol: str = "", limit: int = 200, offset: int = 0, path: Path = DB_PATH) -> dict:
    """Return broker orders aggregated from their individual Flex fills."""
    if start_date is None:
        start_date = cfg.PAPER_PNL_START_DATE
    start_key = str(start_date).replace("-", "")
    side = str(side or "ALL").upper()
    symbol = str(symbol or "").upper().strip()
    where = ["trade_date>=?"]
    params: list[object] = [start_key]
    if side in {"BUY", "SELL"}:
        where.append("side=?")
        params.append(side)
    if symbol:
        where.append("symbol=?")
        params.append(symbol)
    clause = " AND ".join(where)
    group_key = "COALESCE(NULLIF(ib_order_id,''), 'NOORDER:' || source_key)"
    with connect(path) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM flex_executions WHERE {clause} GROUP BY {group_key}, symbol, side)", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT {group_key} AS order_id, symbol, side,
                       MIN(trade_date), MIN(date_time), SUM(quantity),
                       CASE WHEN SUM(quantity)>0 THEN SUM(quantity*price)/SUM(quantity) ELSE 0 END,
                       COUNT(*), SUM(commission), SUM(realized_pnl),
                       MIN(order_type), MIN(flex_confirmed), MAX(trade_date), MAX(date_time)
                FROM flex_executions WHERE {clause}
                GROUP BY order_id, symbol, side
                ORDER BY MAX(trade_date) DESC, MAX(date_time) DESC
                LIMIT ? OFFSET ?""",
            [*params, int(limit), int(offset)],
        ).fetchall()
    keys = ["ib_order_id","symbol","side","trade_date","first_fill_time","quantity","average_price",
            "fill_count","commission","realized_pnl","order_type","flex_confirmed","last_trade_date","last_fill_time"]
    orders = [dict(zip(keys, row)) for row in rows]
    # Add API-observed fills that Flex has not confirmed yet. They are grouped
    # by broker order ID and never contribute provisional P&L/commission.
    with connect(path) as conn:
        pending = conn.execute(
            """SELECT COALESCE(NULLIF(n.ib_order_id,''),'API:'||n.exec_id), n.symbol, n.side,
                      MIN(n.execution_time), SUM(n.quantity),
                      CASE WHEN SUM(n.quantity)>0 THEN SUM(n.quantity*n.price)/SUM(n.quantity) ELSE 0 END,
                      COUNT(*),
                      CASE WHEN COUNT(n.commission)=COUNT(*) THEN SUM(n.commission) ELSE NULL END,
                      CASE WHEN COUNT(n.realized_pnl)=COUNT(*) THEN SUM(n.realized_pnl) ELSE NULL END
               FROM execution_notifications n
               WHERE n.first_seen_source='IBKR_API'
                 AND n.flex_confirmed_at_utc IS NULL
                 AND NOT EXISTS (SELECT 1 FROM flex_executions f WHERE f.ib_exec_id=n.exec_id)
                 AND (?='ALL' OR n.side=?) AND (?='' OR n.symbol=?)
               GROUP BY COALESCE(NULLIF(n.ib_order_id,''),'API:'||n.exec_id), n.symbol, n.side""",
            (side, side, symbol, symbol),
        ).fetchall()
    for oid, sym, sd, dt, qty, avg, fills, commission, realized_pnl in pending:
        # IBKR API CommissionReport exposes commission as a positive cost, while
        # Flex stores costs as negative values. Normalize human-facing history
        # to the Flex convention so pending and confirmed rows are comparable.
        normalized_commission = -abs(float(commission)) if commission is not None else None
        orders.append({"ib_order_id": oid, "symbol": sym, "side": sd, "trade_date": str(dt or "")[:10].replace("-", ""),
                       "first_fill_time": dt, "quantity": qty, "average_price": avg, "fill_count": fills,
                       "commission": normalized_commission, "realized_pnl": realized_pnl, "order_type": "", "flex_confirmed": 0,
                       "last_trade_date": str(dt or "")[:10].replace("-", ""), "last_fill_time": dt})
    orders.sort(key=lambda x: str(x.get("last_fill_time") or x.get("last_trade_date") or ""), reverse=True)
    return {"orders": orders[:int(limit)], "total_orders": int(total) + len(pending), "limit": int(limit), "offset": int(offset), "start_date": start_date, "side": side, "symbol": symbol,
            "pending_flex_orders": len(pending)}


def pnl_summary(path: Path = DB_PATH, start_date: str | None = None) -> dict:
    """Return current realized P&L without double-counting API fills later confirmed by Flex.

    Flex is the durable accounting source. IBKR API execution/commission reports
    are included provisionally only while that execution has not yet appeared in
    Flex. Once Flex confirms it, the provisional contribution disappears.
    """
    if start_date is None:
        try:
            import config as cfg
            start_date = cfg.PAPER_PNL_START_DATE
        except Exception:
            start_date = "2026-09-01"
    start_key = str(start_date).replace("-", "")
    start_iso = str(start_date)[:10]
    with connect(path) as conn:
        confirmed_total, first_trade, last_trade = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl),0), MIN(trade_date), MAX(trade_date) FROM flex_executions WHERE trade_date>=?",
            (start_key,),
        ).fetchone()
        confirmed_commission = conn.execute(
            "SELECT COALESCE(SUM(commission),0) FROM flex_executions WHERE trade_date>=?", (start_key,)
        ).fetchone()[0]

        pending_total, pending_commission_raw, pending_count, pending_through = conn.execute(
            """SELECT COALESCE(SUM(COALESCE(n.realized_pnl,0)),0),
                      COALESCE(SUM(CASE WHEN n.commission IS NULL THEN 0 ELSE ABS(n.commission) END),0),
                      COUNT(*),
                      MAX(COALESCE(NULLIF(n.execution_time,''), n.observed_at_utc))
               FROM execution_notifications n
               WHERE n.flex_confirmed_at_utc IS NULL
                 AND NOT EXISTS (SELECT 1 FROM flex_executions f WHERE f.ib_exec_id=n.exec_id)
                 AND substr(COALESCE(NULLIF(n.execution_time,''), n.observed_at_utc),1,10) >= ?""",
            (start_iso,),
        ).fetchone()
        pending_commission = -abs(float(pending_commission_raw or 0))

        per_symbol_map = {
            s: float(pnl or 0)
            for s, pnl in conn.execute(
                """SELECT symbol, COALESCE(SUM(realized_pnl),0)
                   FROM flex_executions WHERE trade_date>=? GROUP BY symbol ORDER BY symbol""",
                (start_key,),
            ).fetchall()
        }
        for symbol, pnl in conn.execute(
            """SELECT n.symbol, COALESCE(SUM(COALESCE(n.realized_pnl,0)),0)
               FROM execution_notifications n
               WHERE n.flex_confirmed_at_utc IS NULL
                 AND NOT EXISTS (SELECT 1 FROM flex_executions f WHERE f.ib_exec_id=n.exec_id)
                 AND substr(COALESCE(NULLIF(n.execution_time,''), n.observed_at_utc),1,10) >= ?
               GROUP BY n.symbol""",
            (start_iso,),
        ).fetchall():
            per_symbol_map[str(symbol)] = per_symbol_map.get(str(symbol), 0.0) + float(pnl or 0)

    confirmed_total = float(confirmed_total or 0)
    pending_total = float(pending_total or 0)
    current_total = confirmed_total + pending_total
    current_commission = float(confirmed_commission or 0) + pending_commission
    return {
        "realized_pnl_since_start": current_total,
        "confirmed_realized_pnl": confirmed_total,
        "pending_realized_pnl": pending_total,
        "commissions_since_start": current_commission,
        "confirmed_commissions": float(confirmed_commission or 0),
        "pending_commissions": pending_commission,
        "pending_execution_count": int(pending_count or 0),
        "pending_through": pending_through,
        "pnl_start_date": start_date,
        "first_imported_trade_on_or_after_start": first_trade,
        "through": last_trade,
        "per_symbol": [
            {"symbol": symbol, "realized_pnl": pnl}
            for symbol, pnl in sorted(per_symbol_map.items())
        ],
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
