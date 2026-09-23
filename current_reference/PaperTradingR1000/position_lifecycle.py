"""Position lifecycle evidence and holding-day calculations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from automated_order_store import load_store
from flex_execution_ledger import connect as ledger_connect
try:
    from .symbol_mapping import canonical_symbol
except ImportError:
    from symbol_mapping import canonical_symbol


def _date_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) >= 10 and "-" in text[:10]:
        return text[:10].replace("-", "")
    digits = "".join(ch for ch in text[:10] if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _submitted_trade_date(order: dict[str, Any]) -> str:
    raw = str(order.get("submitted_at_utc") or order.get("created_at_utc") or "")
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # US orders in this system are submitted during the same UTC/ET date.
        return dt.date().strftime("%Y%m%d")
    except ValueError:
        return _date_key(raw)


def infer_current_long_entry_date(symbol: str, current_quantity: float) -> str:
    """Infer start date of the currently open long using durable broker evidence.

    Preference: Flex fills, reconstructed as a position ledger. If Flex has not
    yet covered a recent fill, fall back to the latest automated BUY submission
    for a symbol that is currently held at the broker.
    """
    symbol = canonical_symbol(symbol)
    if not symbol or float(current_quantity or 0) <= 0:
        return ""

    # Reconstruct the current open long cycle from confirmed Flex fills.
    try:
        with ledger_connect() as conn:
            rows = conn.execute(
                """SELECT trade_date, side, quantity
                   FROM flex_executions
                   WHERE symbol=?
                   ORDER BY trade_date, date_time, id""",
                (symbol,),
            ).fetchall()
        qty = 0.0
        current_entry = ""
        for trade_date, side, quantity in rows:
            q = abs(float(quantity or 0))
            if str(side or "").upper() == "BUY":
                if qty <= 1e-9:
                    current_entry = _date_key(trade_date)
                qty += q
            elif str(side or "").upper() == "SELL":
                qty -= q
                if qty <= 1e-9:
                    qty = 0.0
                    current_entry = ""
        if qty > 1e-9 and current_entry:
            return current_entry
    except Exception:
        pass

    # Recent fills may not yet be present in Flex. A live broker position plus
    # our own latest automated BUY submission is valid fallback evidence.
    try:
        orders = [
            row for row in (load_store().get("orders") or [])
            if canonical_symbol(row.get("symbol")) == symbol
            and str(row.get("side") or "").upper() == "BUY"
            and row.get("submitted_at_utc")
        ]
        if orders:
            orders.sort(key=lambda row: str(row.get("submitted_at_utc") or ""), reverse=True)
            return _submitted_trade_date(orders[0])
    except Exception:
        pass
    return ""


def holding_trading_days(entry_date: str, completed_session_dates: list[str]) -> int:
    """Count completed trading sessions from entry session inclusive."""
    entry = _date_key(entry_date)
    if not entry:
        return 0
    dates = sorted({_date_key(d) for d in completed_session_dates if _date_key(d)})
    return sum(1 for d in dates if d >= entry)
