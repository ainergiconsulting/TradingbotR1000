"""One Telegram notification per fully completed automated broker order."""

from __future__ import annotations

from typing import Any

from automated_order_store import load_store, save_store
from flex_execution_ledger import (
    connect as ledger_connect,
    mark_execution_notified,
    observe_execution,
)
from monitoring_io import utc_timestamp
from telegram_alerts import alert_execution_filled
try:
    from .symbol_mapping import canonical_symbol
except ImportError:
    from symbol_mapping import canonical_symbol


def _ensure_completion_table(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS order_completion_notifications (
            order_key TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            expected_quantity REAL NOT NULL,
            filled_quantity REAL NOT NULL,
            average_price REAL,
            source TEXT,
            telegram_notified_at_utc TEXT NOT NULL
        )
    """)


def _find_automated_order(*, symbol: str, side: str, api_order_id: str = "", trade_date: str = "") -> dict[str, Any] | None:
    symbol = canonical_symbol(symbol)
    side = str(side or "").upper()
    candidates = [
        row for row in (load_store().get("orders") or [])
        if canonical_symbol(row.get("symbol")) == symbol
        and str(row.get("side") or "").upper() == side
        and row.get("submitted_at_utc")
    ]
    if api_order_id:
        for row in candidates:
            if str(row.get("ibkr_order_id") or "") == str(api_order_id):
                return row
    if trade_date:
        key = str(trade_date).replace("-", "")[:8]
        same_day = [
            row for row in candidates
            if str(row.get("submitted_at_utc") or "")[:10].replace("-", "") == key
        ]
        if same_day:
            same_day.sort(key=lambda row: str(row.get("submitted_at_utc") or ""), reverse=True)
            return same_day[0]
    candidates.sort(key=lambda row: str(row.get("submitted_at_utc") or ""), reverse=True)
    return candidates[0] if candidates else None


def _already_notified(order_key: str) -> bool:
    with ledger_connect() as conn:
        _ensure_completion_table(conn)
        row = conn.execute(
            "SELECT 1 FROM order_completion_notifications WHERE order_key=?",
            (str(order_key),),
        ).fetchone()
        conn.commit()
        return bool(row)


def _mark_order_notified(order: dict[str, Any], *, filled_quantity: float, average_price: float, source: str) -> None:
    with ledger_connect() as conn:
        _ensure_completion_table(conn)
        conn.execute(
            """INSERT OR IGNORE INTO order_completion_notifications
               (order_key,symbol,side,expected_quantity,filled_quantity,average_price,source,telegram_notified_at_utc)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                str(order.get("order_key") or ""),
                canonical_symbol(order.get("symbol")),
                str(order.get("side") or "").upper(),
                float(order.get("quantity") or 0),
                float(filled_quantity or 0),
                float(average_price or 0),
                str(source or ""),
                utc_timestamp(),
            ),
        )
        conn.commit()


def _aggregate_api_order(api_order_id: str) -> tuple[float, float, str, list[str]]:
    with ledger_connect() as conn:
        rows = conn.execute(
            """SELECT exec_id, quantity, price, execution_time
               FROM execution_notifications WHERE ib_order_id=?""",
            (str(api_order_id),),
        ).fetchall()
    qty = sum(float(r[1] or 0) for r in rows)
    weighted = sum(float(r[1] or 0) * float(r[2] or 0) for r in rows)
    avg = weighted / qty if qty > 0 else 0.0
    last_time = max((str(r[3] or "") for r in rows), default="")
    return qty, avg, last_time, [str(r[0]) for r in rows]


def _aggregate_flex_order(flex_order_id: str) -> tuple[float, float, str, list[str]]:
    with ledger_connect() as conn:
        rows = conn.execute(
            """SELECT ib_exec_id, quantity, price, date_time
               FROM flex_executions WHERE ib_order_id=?""",
            (str(flex_order_id),),
        ).fetchall()
    qty = sum(float(r[1] or 0) for r in rows)
    weighted = sum(float(r[1] or 0) * float(r[2] or 0) for r in rows)
    avg = weighted / qty if qty > 0 else 0.0
    last_time = max((str(r[3] or "") for r in rows), default="")
    return qty, avg, last_time, [str(r[0]) for r in rows if r[0]]


def process_execution(
    *,
    exec_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    execution_time: str = "",
    api_order_id: str = "",
    flex_order_id: str = "",
    trade_date: str = "",
    source: str,
) -> bool:
    """Persist one fill; alert exactly once only when the whole order is filled."""
    observe_execution(
        exec_id,
        source=source,
        symbol=canonical_symbol(symbol),
        side=str(side or "").upper(),
        quantity=float(quantity or 0),
        price=float(price or 0),
        execution_time=str(execution_time or ""),
        ib_order_id=str(api_order_id or ""),
    )

    order = _find_automated_order(
        symbol=symbol,
        side=side,
        api_order_id=api_order_id,
        trade_date=trade_date,
    )
    if not order:
        return False

    expected = float(order.get("quantity") or 0)
    if expected <= 0 or not order.get("order_key"):
        return False

    if str(source).upper() == "FLEX" and flex_order_id:
        filled, avg, last_time, exec_ids = _aggregate_flex_order(flex_order_id)
    elif api_order_id:
        filled, avg, last_time, exec_ids = _aggregate_api_order(api_order_id)
    else:
        return False

    if filled + 1e-7 < expected:
        return False
    if _already_notified(str(order["order_key"])):
        for eid in exec_ids:
            mark_execution_notified(eid)
        return False

    alert_execution_filled({
        "symbol": canonical_symbol(symbol),
        "side": str(side or "").upper(),
        "quantity": expected,
        "price": avg,
        "date_time": last_time or execution_time,
        "source": f"{source} — order fully filled",
    })
    _mark_order_notified(order, filled_quantity=filled, average_price=avg, source=source)
    for eid in exec_ids:
        mark_execution_notified(eid)

    # Keep the durable automated-order state consistent with broker execution evidence.
    store = load_store()
    for row in store.get("orders") or []:
        if row.get("order_key") == order.get("order_key"):
            row["filled_quantity"] = filled
            row["remaining_quantity"] = max(0.0, expected - filled)
            row["average_fill_price"] = avg
            row["broker_status"] = "Filled"
            row["updated_at_utc"] = utc_timestamp()
            row.setdefault("status_history", []).append({
                "timestamp_utc": utc_timestamp(),
                "broker_status": "Filled",
                "filled_quantity": filled,
                "remaining_quantity": 0.0,
                "average_fill_price": avg,
                "reason": "order_completion_evidence",
            })
            row["status_history"] = row["status_history"][-50:]
            break
    save_store(store)
    return True
