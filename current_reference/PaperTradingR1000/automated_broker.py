"""Dedicated automated PAPER broker adapter for TradingbotR1000."""

from __future__ import annotations

from datetime import datetime, timezone
from math import floor, isfinite
from typing import Any

import config as cfg
from automated_order_store import (
    find_duplicate,
    normalize_broker_status,
    order_identity,
    update_order_status,
    upsert_order_intent,
)
from ibkr_utils import connect, stock_contract
from logger_utils import log
from monitoring_io import atomic_write_json, utc_timestamp
try:
    from ib_insync import LimitOrder, MarketOrder
except Exception:  # pragma: no cover - dependency availability is environment-specific.
    LimitOrder = None
    MarketOrder = None


class AutomatedBrokerError(RuntimeError):
    """Raised when automated order execution must fail closed."""


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def _account_values(broker_context: dict[str, Any]) -> dict[str, float]:
    values = broker_context.get("account_values") or {}
    return {
        "net_liquidation": _as_float(values.get("net_liquidation")),
        "cash": _as_float(values.get("cash")),
        "available_funds": _as_float(values.get("available_funds")),
        "buying_power": _as_float(values.get("buying_power")),
    }


def _signal_date(scan: dict[str, Any], symbol: str) -> str:
    dates = scan.get("signal_dates") or {}
    return str(dates.get(symbol) or scan.get("market_data_latest_date") or scan.get("timestamp_utc", "")[:10])


def _cycle_id(scan: dict[str, Any]) -> str:
    return str(scan.get("cycle_id") or scan.get("timestamp_utc") or utc_timestamp())


def _buy_intents(scan: dict[str, Any], broker_context: dict[str, Any]) -> list[dict[str, Any]]:
    values = _account_values(broker_context)
    cash_remaining = min(values["cash"], values["available_funds"], values["buying_power"])
    capital_control = scan.get("investable_capital_control") or {}
    capital_compliance = str(capital_control.get("compliance") or "OK").upper()
    buy_block_reason = ""
    if capital_compliance != "OK":
        buy_block_reason = str(capital_control.get("reason") or "investable_capital_compliance_failed")
    if scan.get("buy_submission_blocked"):
        buy_block_reason = str(scan.get("buy_submission_block_reason") or buy_block_reason or "buy_submission_blocked")
    intents = []
    for row in scan.get("order_plans", []) or []:
        symbol = str(row.get("symbol") or "").upper()
        limit_price = _as_float(row.get("limit_price"))
        allocation = _as_float(row.get("allocation_value"))
        quantity = floor(allocation / limit_price) if limit_price > 0 else 0
        notional = quantity * limit_price
        rejection = ""
        if buy_block_reason:
            rejection = buy_block_reason
        elif quantity <= 0:
            rejection = "calculated_quantity_not_positive"
        elif notional > cash_remaining + 1e-9:
            rejection = "insufficient_cash_or_buying_power"
        else:
            cash_remaining -= notional
        intents.append(
            {
                "bot": cfg.BOT_NAME,
                "cycle_id": _cycle_id(scan),
                "symbol": symbol,
                "side": "BUY",
                "quantity": float(quantity),
                "order_type": "LIMIT",
                "limit_price": limit_price,
                "allocation_value": allocation,
                "estimated_notional": notional,
                "signal_date": _signal_date(scan, symbol),
                "strategy_signal_date": _signal_date(scan, symbol),
                "strategy_version": scan.get("strategy_version"),
                "configuration_sha256": scan.get("configuration_sha256"),
                "reason": "entry_bollinger_pullback_trend",
                "rejection_reason": rejection,
            }
        )
    return intents


def _sell_intents(scan: dict[str, Any], broker_context: dict[str, Any]) -> list[dict[str, Any]]:
    positions = {
        str(row.get("symbol") or "").upper(): row
        for row in broker_context.get("positions", []) or []
        if _as_float(row.get("quantity") or row.get("position")) > 0
    }
    intents = []
    for row in scan.get("sell_order_plans", []) or []:
        symbol = str(row.get("symbol") or "").upper()
        quantity = _as_float(row.get("quantity") or (positions.get(symbol) or {}).get("quantity"))
        rejection = "" if quantity > 0 else "no_live_position_quantity"
        intents.append(
            {
                "bot": cfg.BOT_NAME,
                "cycle_id": _cycle_id(scan),
                "symbol": symbol,
                "side": "SELL",
                "quantity": float(quantity),
                "order_type": "MARKET",
                "limit_price": None,
                "allocation_value": None,
                "estimated_notional": None,
                "signal_date": _signal_date(scan, symbol),
                "strategy_signal_date": _signal_date(scan, symbol),
                "strategy_version": scan.get("strategy_version"),
                "configuration_sha256": scan.get("configuration_sha256"),
                "reason": row.get("reason") or "exit_signal",
                "rejection_reason": rejection,
            }
        )
    return intents


def build_intended_orders(scan: dict[str, Any], broker_context: dict[str, Any]) -> list[dict[str, Any]]:
    return _sell_intents(scan, broker_context) + _buy_intents(scan, broker_context)


def _broker_status_from_trade(trade: Any) -> dict[str, Any]:
    order = getattr(trade, "order", None)
    status = getattr(trade, "orderStatus", None)
    return {
        "broker_status": normalize_broker_status(getattr(status, "status", "")),
        "ibkr_order_id": getattr(order, "orderId", None),
        "perm_id": getattr(order, "permId", None),
        "filled_quantity": getattr(status, "filled", None),
        "remaining_quantity": getattr(status, "remaining", None),
        "average_fill_price": getattr(status, "avgFillPrice", None),
    }


def _build_ibkr_order(intent: dict[str, Any]) -> Any:
    side = str(intent.get("side") or "").upper()
    quantity = _as_float(intent.get("quantity"))
    order_type = str(intent.get("order_type") or "").upper()
    if order_type == "LIMIT":
        if LimitOrder is None:
            raise AutomatedBrokerError("ib_insync_limit_order_unavailable")
        return LimitOrder(side, quantity, _as_float(intent.get("limit_price")))
    if order_type == "MARKET":
        if MarketOrder is None:
            raise AutomatedBrokerError("ib_insync_market_order_unavailable")
        return MarketOrder(side, quantity)
    raise AutomatedBrokerError(f"unsupported_order_type:{order_type}")


def _ensure_execution_allowed(broker_context: dict[str, Any]) -> None:
    if not cfg.EXECUTE_ORDERS:
        raise AutomatedBrokerError(f"automated_execution_disabled:{cfg.AUTOMATED_PAPER_EXECUTION_SWITCH}")
    if cfg.PAPER_TRADING_REQUIRED and broker_context.get("account_mode") != "PAPER":
        raise AutomatedBrokerError("paper_account_not_confirmed")
    from gateway_status import collect_system_health

    health = collect_system_health()
    if health.get("market_status") != "OPEN" or health.get("liquid_hours_status") != "IN":
        raise AutomatedBrokerError(
            "outside_liquid_hours:"
            f"market={health.get('market_status')} liquid_hours={health.get('liquid_hours_status')}"
        )


def process_order_plan(
    scan: dict[str, Any],
    broker_context: dict[str, Any],
    *,
    transmit: bool | None = None,
) -> dict[str, Any]:
    """Persist, duplicate-check, and optionally transmit automated order intents."""

    transmit_requested = cfg.EXECUTE_ORDERS if transmit is None else bool(transmit)
    transmission_permitted = transmit_requested and cfg.EXECUTE_ORDERS
    if transmit_requested:
        _ensure_execution_allowed(broker_context)

    positions = list(broker_context.get("positions") or [])
    open_orders = list(broker_context.get("open_orders") or [])
    intended = build_intended_orders(scan, broker_context)
    submitted = []
    rejected = []
    duplicate_preventions = []
    persisted = []

    ib = None
    if transmission_permitted:
        ib = connect(client_id=cfg.CLIENT_ID, readonly=False)
    try:
        for intent in intended:
            duplicate_reason = find_duplicate(
                intent,
                positions=positions,
                open_orders=open_orders,
                include_dry_run=not transmission_permitted,
            )
            if duplicate_reason:
                row = upsert_order_intent(intent, broker_status="NotTransmitted", reason=duplicate_reason)
                duplicate_preventions.append({"symbol": intent["symbol"], "side": intent["side"], "reason": duplicate_reason})
                persisted.append(row)
                continue
            if intent.get("rejection_reason"):
                row = upsert_order_intent(intent, broker_status="Rejected", reason=intent["rejection_reason"])
                rejected.append({"symbol": intent["symbol"], "side": intent["side"], "reason": intent["rejection_reason"]})
                persisted.append(row)
                continue
            if not transmission_permitted:
                row = upsert_order_intent(intent, broker_status="NotTransmitted", reason="automated_execution_disabled")
                persisted.append(row)
                continue

            contract = stock_contract(intent["symbol"])
            qualified = ib.qualifyContracts(contract)
            if qualified:
                contract = qualified[0]
            order = _build_ibkr_order(intent)
            intent["submitted_at_utc"] = utc_timestamp()
            row = upsert_order_intent(intent, broker_status="PendingSubmit", reason="submitted_to_ibkr")
            trade = ib.placeOrder(contract, order)
            ib.sleep(2)
            broker = _broker_status_from_trade(trade)
            update_order_status(order_key=row["order_key"], **broker)
            submitted.append({"symbol": intent["symbol"], "side": intent["side"], **broker})
    except Exception as exc:
        log("automated order processing failed", level="ERROR", extra={"error": repr(exc)})
        raise
    finally:
        if ib is not None:
            ib.disconnect()

    report = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "cycle_id": _cycle_id(scan),
        "transmit_requested": transmit_requested,
        "transmission_permitted": transmission_permitted,
        "authorization_switch": cfg.AUTOMATED_PAPER_EXECUTION_SWITCH,
        "account_mode": broker_context.get("account_mode", "UNKNOWN"),
        "account_values": _account_values(broker_context),
        "intended_orders": intended,
        "persisted_orders": persisted,
        "submitted_orders": submitted,
        "rejected_orders": rejected,
        "duplicate_preventions": duplicate_preventions,
        "broker_orders_transmitted": len(submitted),
        "proof_no_broker_order_transmitted": not transmission_permitted and len(submitted) == 0,
    }
    atomic_write_json(cfg.AUTOMATED_EXECUTION_REPORT_FILE, report)
    log(
        "automated order plan processed",
        extra={
            "cycle_id": report["cycle_id"],
            "intended": len(intended),
            "submitted": len(submitted),
            "duplicates": len(duplicate_preventions),
            "transmission_permitted": transmission_permitted,
        },
    )
    return report


def simulated_status_update(order_key: str, status: str, **extra: Any) -> dict[str, Any] | None:
    """Test helper for broker-status state transitions without IBKR calls."""

    return update_order_status(order_key=order_key, broker_status=status, **extra)
