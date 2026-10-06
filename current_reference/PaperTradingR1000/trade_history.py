"""Durable descriptive history of completed TradingbotR1000 trades.

This module is intentionally read-only with respect to broker orders. It builds
one immutable/descriptive row per completed long trade from IBKR Flex fills and
IBKR one-minute historical bars. It contains no stop-loss research, simulation,
or trading decision logic.
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ib_insync import IB, Stock

import config as cfg
from automated_order_store import load_store
from strategy import rsi_values

ET = ZoneInfo("US/Eastern")
DB_PATH = cfg.EXECUTION_HISTORY_DB
BARS_DIR = cfg.PROJECT_ROOT / "data" / "daily_bars"


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ensure_table(conn)
    return conn


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS trade_history (
            trade_key TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            buy_date TEXT NOT NULL,
            buy_first_fill TEXT NOT NULL,
            buy_last_fill TEXT NOT NULL,
            buy_vwap REAL NOT NULL,
            sell_date TEXT NOT NULL,
            sell_first_fill TEXT NOT NULL,
            sell_last_fill TEXT NOT NULL,
            sell_vwap REAL NOT NULL,
            min_price REAL,
            min_time TEXT,
            max_price REAL,
            max_time TEXT,
            mae_abs_per_share REAL,
            mae_pct REAL,
            mfe_abs_per_share REAL,
            mfe_pct REAL,
            realized_pnl REAL,
            pnl_pct REAL,
            buy_commission REAL,
            sell_commission REAL,
            total_commission REAL,
            calendar_days INTEGER,
            trading_sessions INTEGER,
            exit_reason TEXT,
            entry_rsi2 REAL,
            exit_rsi2 REAL,
            data_quality TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        )"""
    )
    conn.commit()


def _flex_closed_trades(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = [
        dict(row)
        for row in conn.execute(
            """SELECT trade_date,symbol,side,
                      SUM(quantity) AS quantity,
                      SUM(quantity*price)/SUM(quantity) AS vwap,
                      SUM(COALESCE(realized_pnl,0)) AS pnl,
                      SUM(COALESCE(commission,0)) AS commission,
                      MIN(date_time) AS first_fill,
                      MAX(date_time) AS last_fill
               FROM flex_executions
               WHERE flex_confirmed=1
               GROUP BY trade_date,symbol,side
               ORDER BY trade_date, first_fill"""
        )
    ]
    open_buys: dict[str, list[dict[str, Any]]] = {}
    completed: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row["symbol"]).upper()
        side = str(row["side"]).upper()
        if side == "BUY":
            open_buys.setdefault(symbol, []).append(row)
        elif side == "SELL" and open_buys.get(symbol):
            buy = open_buys[symbol].pop(0)
            completed.append({"buy": buy, "sell": row})
    return completed


def _parse_fill_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d;%H%M%S").replace(tzinfo=ET)


def _trade_key(symbol: str, buy: dict[str, Any], sell: dict[str, Any]) -> str:
    return f"{symbol}:{buy['first_fill']}:{sell['last_fill']}"


def _load_daily_bars(symbol: str) -> list[dict[str, str]]:
    path = BARS_DIR / f"{symbol}.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _rsi_before_date(symbol: str, yyyymmdd: str) -> float | None:
    rows = _load_daily_bars(symbol)
    closes = [
        float(row["close"])
        for row in rows
        if str(row.get("date") or "") < yyyymmdd and row.get("close") not in (None, "")
    ]
    if len(closes) < 4:
        return None
    try:
        return float(rsi_values(closes, period=2)[-1])
    except (ValueError, ZeroDivisionError):
        return None


def _trading_sessions(symbol: str, buy_date: str, sell_date: str) -> int | None:
    rows = _load_daily_bars(symbol)
    if not rows:
        return None
    dates = {
        str(row.get("date") or "")
        for row in rows
        if buy_date <= str(row.get("date") or "") <= sell_date
    }
    return len(dates)


def _exit_reason(symbol: str, sell_date: str, quantity: float) -> str:
    try:
        orders = load_store().get("orders") or []
    except Exception:
        return ""
    matches = []
    for row in orders:
        if str(row.get("side") or "").upper() != "SELL":
            continue
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        submitted = str(row.get("submitted_at_utc") or "")
        if submitted[:10].replace("-", "") != sell_date:
            continue
        if float(row.get("quantity") or 0) <= 0:
            continue
        matches.append(row)
    if not matches:
        return ""
    matches.sort(key=lambda row: abs(float(row.get("quantity") or 0) - quantity))
    return str(matches[0].get("reason") or "")


def _historical_extrema(ib: IB, symbol: str, start: datetime, end: datetime) -> dict[str, Any]:
    contract = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(contract)
    duration_days = max(2, (end.date() - start.date()).days + 2)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime=end.strftime("%Y%m%d %H:%M:%S US/Eastern"),
        durationStr=f"{duration_days} D",
        barSizeSetting="1 min",
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
        keepUpToDate=False,
    )
    start_minute = start.replace(second=0, microsecond=0)
    end_minute = end.replace(second=0, microsecond=0)
    held = [bar for bar in bars if start_minute <= bar.date <= end_minute]
    if not held:
        raise RuntimeError(f"no_1min_bars_for_trade:{symbol}")
    low_bar = min(held, key=lambda bar: float(bar.low))
    high_bar = max(held, key=lambda bar: float(bar.high))
    return {
        "min_price": float(low_bar.low),
        "min_time": low_bar.date.isoformat(),
        "max_price": float(high_bar.high),
        "max_time": high_bar.date.isoformat(),
    }


def refresh_missing_trade_history(path: Path = DB_PATH) -> dict[str, Any]:
    """Backfill only completed Flex trades not already in trade_history.

    Opens a short-lived read-only IBKR client only when a missing closed trade
    actually requires one-minute historical bars.
    """
    with connect(path) as conn:
        completed = _flex_closed_trades(conn)
        existing = {
            row[0]
            for row in conn.execute("SELECT trade_key FROM trade_history").fetchall()
        }
    missing = []
    for item in completed:
        symbol = str(item["buy"]["symbol"]).upper()
        key = _trade_key(symbol, item["buy"], item["sell"])
        if key not in existing:
            missing.append((key, symbol, item["buy"], item["sell"]))
    if not missing:
        return {"status": "UP_TO_DATE", "inserted": 0, "total_closed": len(completed)}

    ib = IB()
    inserted = 0
    errors: list[str] = []
    try:
        ib.connect(
            cfg.HOST,
            cfg.PORT,
            clientId=cfg.TRADE_HISTORY_CLIENT_ID,
            readonly=True,
            timeout=8,
        )
        for key, symbol, buy, sell in missing:
            try:
                start = _parse_fill_time(str(buy["first_fill"]))
                end = _parse_fill_time(str(sell["last_fill"]))
                extrema = _historical_extrema(ib, symbol, start, end)
                entry = float(buy["vwap"])
                exit_price = float(sell["vwap"])
                min_price = float(extrema["min_price"])
                max_price = float(extrema["max_price"])
                quantity = float(buy["quantity"])
                payload = (
                    key, symbol, quantity,
                    str(buy["trade_date"]), str(buy["first_fill"]), str(buy["last_fill"]), entry,
                    str(sell["trade_date"]), str(sell["first_fill"]), str(sell["last_fill"]), exit_price,
                    min_price, extrema["min_time"], max_price, extrema["max_time"],
                    min_price-entry, (min_price/entry)-1,
                    max_price-entry, (max_price/entry)-1,
                    float(sell["pnl"] or 0), (exit_price/entry)-1,
                    float(buy["commission"] or 0), float(sell["commission"] or 0),
                    float(buy["commission"] or 0)+float(sell["commission"] or 0),
                    (end.date()-start.date()).days,
                    _trading_sessions(symbol, str(buy["trade_date"]), str(sell["trade_date"])),
                    _exit_reason(symbol, str(sell["trade_date"]), quantity),
                    _rsi_before_date(symbol, str(buy["trade_date"])),
                    _rsi_before_date(symbol, str(sell["trade_date"])),
                    "IBKR_FLEX+IBKR_1MIN",
                    datetime.now().astimezone().astimezone(ZoneInfo("UTC")).replace(microsecond=0).isoformat().replace("+00:00","Z"),
                )
                with connect(path) as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO trade_history VALUES (
                            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                        )""",
                        payload,
                    )
                    conn.commit()
                inserted += 1
            except Exception as exc:
                errors.append(f"{symbol}:{type(exc).__name__}:{exc}")
    finally:
        if ib.isConnected():
            ib.disconnect()
    return {
        "status": "OK" if not errors else "PARTIAL",
        "inserted": inserted,
        "errors": errors,
        "total_closed": len(completed),
    }


def list_trade_history(path: Path = DB_PATH, limit: int = 500, offset: int = 0) -> dict[str, Any]:
    with connect(path) as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM trade_history").fetchone()[0])
        rows = [
            dict(row)
            for row in conn.execute(
                """SELECT * FROM trade_history
                   ORDER BY sell_date DESC, sell_last_fill DESC
                   LIMIT ? OFFSET ?""",
                (int(limit), int(offset)),
            ).fetchall()
        ]
    return {
        "total_trades": total,
        "limit": int(limit),
        "offset": int(offset),
        "source": "IBKR_FLEX+IBKR_1MIN",
        "research_or_simulation": False,
        "trades": rows,
    }
