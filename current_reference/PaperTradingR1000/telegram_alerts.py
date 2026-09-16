"""Operational alert rendering for TradingbotR1000."""

from __future__ import annotations

from typing import Any
import time

import config as cfg
from alert_utils import write_alert


def alert_scan_completed(
    selected_count: int,
    planned_count: int,
    rejected_or_skipped_count: int,
    broker_submitted_count: int,
    effective_investable_capital: float,
    planned_orders: list[dict[str, Any]] | None = None,
    submitted_orders: list[dict[str, Any]] | None = None,
) -> None:
    planned_orders = list(planned_orders or [])
    submitted_orders = list(submitted_orders or [])
    planned_lines = []
    for row in planned_orders:
        side = str(row.get("side") or "?").upper()
        symbol = str(row.get("symbol") or "?").upper()
        qty = row.get("quantity")
        order_type = str(row.get("order_type") or "?").upper()
        limit_price = row.get("limit_price")
        detail = f"- {side} {symbol} | qty {qty} | {order_type}"
        if order_type == "LIMIT" and limit_price is not None:
            try:
                detail += f" @ ${float(limit_price):,.2f}"
            except (TypeError, ValueError):
                detail += f" @ {limit_price}"
        rejection = str(row.get("rejection_reason") or "").strip()
        if rejection:
            detail += f" | BLOCKED: {rejection}"
        planned_lines.append(detail)

    submitted_lines = []
    for row in submitted_orders:
        side = str(row.get("side") or "?").upper()
        symbol = str(row.get("symbol") or "?").upper()
        status = str(row.get("broker_status") or "UNKNOWN")
        filled = row.get("filled_quantity")
        remaining = row.get("remaining_quantity")
        submitted_lines.append(f"- {side} {symbol} | {status} | filled {filled} | remaining {remaining}")

    message = (
        "R1000 scan completed.\n"
        f"Selected candidates: {selected_count}\n"
        f"Planned orders: {planned_count}\n"
        f"Rejected/skipped: {rejected_or_skipped_count}\n"
        f"Broker submitted: {broker_submitted_count}\n"
        f"Operational buy budget: ${effective_investable_capital:,.2f}"
    )
    if planned_lines:
        message += "\n\nPLANNED:\n" + "\n".join(planned_lines)
    if submitted_lines:
        message += "\n\nSUBMITTED/PENDING:\n" + "\n".join(submitted_lines)
    write_alert("scan_completed", message, extra={"planned_orders": planned_orders, "submitted_orders": submitted_orders})


def alert_execution_filled(fill: dict[str, Any]) -> None:
    side = str(fill.get("side") or "?").upper()
    symbol = str(fill.get("symbol") or "?").upper()
    quantity = fill.get("quantity")
    price = fill.get("price")
    proceeds = fill.get("proceeds")
    realized_pnl = fill.get("realized_pnl")
    commission = fill.get("commission")
    date_time = str(fill.get("date_time") or fill.get("trade_date") or "")
    lines = [
        f"{side} FILLED — {symbol}",
        f"Quantity: {quantity}",
        f"Fill price: ${float(price or 0):,.2f}",
        f"Timestamp: {date_time}",
    ]
    if proceeds is not None:
        lines.append(f"Proceeds/notional: ${abs(float(proceeds or 0)):,.2f}")
    if side == "SELL" and realized_pnl is not None:
        lines.append(f"Realized P&L: ${float(realized_pnl or 0):,.2f}")
    if commission is not None:
        lines.append(f"Commission: ${abs(float(commission or 0)):,.2f}")
    lines.append(f"Source: {str(fill.get('source') or 'IBKR confirmed execution')}")
    write_alert("order_filled", "\n".join(lines), extra=fill)


def alert_engine_failure(error: str, *, extra: dict[str, Any] | None = None) -> None:
    # Persistent anti-spam guard: repeated controller retries or systemd
    # restarts must not generate a Telegram storm for the same continuing
    # incident. Health-supervisor transition alerts still report IBKR
    # disconnect/reconnect events independently.
    try:
        recent = max(cfg.ALERTS_DIR.glob("*_engine_failure.json"), key=lambda p: p.stat().st_mtime)
        if time.time() - recent.stat().st_mtime < 6 * 60 * 60:
            return
    except (ValueError, FileNotFoundError, OSError):
        pass
    write_alert("engine_failure", error, extra=extra)


def start_alert_thread(*_args: Any, **_kwargs: Any) -> None:
    return None


def alert_market_data_refresh_failure(detail: str) -> None:
    write_alert(
        "market_data_refresh_failure",
        (
            "R1000 MARKET DATA ALERT.\n"
            "IBKR daily-bar refresh failed.\n"
            "Automated BUY orders will remain fail-closed until current data is confirmed.\n"
            f"Detail: {detail}"
        ),
    )


def alert_market_data_refresh_warning(detail: str) -> None:
    write_alert(
        "market_data_refresh_warning",
        "IBKR market-data refresh completed with a small unresolved symbol set. "
        "Trading may proceed using the validated universe subset. " + detail,
    )


def alert_universe_refresh_failure(detail: str) -> None:
    write_alert(
        "universe_refresh_failure",
        "Weekly IWB/Russell 1000 universe refresh failed. Trading will continue with the last validated universe. " + detail,
    )


def alert_order_status(order: dict[str, Any], status: str) -> None:
    """Send one operator-facing lifecycle alert for a broker order status."""
    normalized = str(status or "UNKNOWN").strip()
    display_status = "PARTIALLY FILLED" if normalized.upper().replace("_", "").replace(" ", "") == "PARTIALLYFILLED" else normalized.upper()
    symbol = str(order.get("symbol") or "?").upper()
    side = str(order.get("side") or "?").upper()
    quantity = order.get("quantity")
    filled = order.get("filled_quantity")
    remaining = order.get("remaining_quantity")
    avg = order.get("average_fill_price")
    rejection = str(order.get("rejection_reason") or "").strip()
    cancellation = str(order.get("cancellation_reason") or "").strip()

    lines = [
        f"{display_status} — {side} {symbol}",
        f"Quantity: {quantity}",
    ]
    if filled is not None:
        lines.append(f"Filled: {filled}")
    if remaining is not None:
        lines.append(f"Remaining: {remaining}")
    if avg not in (None, "", 0, 0.0):
        lines.append(f"Average fill price: ${float(avg):,.2f}")
    if rejection:
        lines.append(f"Reason: {rejection}")
    if cancellation:
        lines.append(f"Reason: {cancellation}")
    write_alert(f"order_{normalized.lower()}", "\n".join(lines), extra=order)
