"""Persistent automated order evidence for TradingbotR1000."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

import config as cfg
from monitoring_io import atomic_write_json, utc_timestamp
try:
    from .symbol_mapping import canonical_symbol
except ImportError:  # pragma: no cover - supports direct script execution.
    from symbol_mapping import canonical_symbol


ACTIVE_BROKER_STATUSES = {
    "PENDINGSUBMIT",
    "PENDING_SUBMIT",
    "PRESUBMITTED",
    "SUBMITTED",
    "PARTIALLYFILLED",
    "PARTIALLY_FILLED",
}
FINAL_BROKER_STATUSES = {"FILLED", "CANCELLED", "APICANCELLED", "INACTIVE", "REJECTED"}


def _parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_broker_status(status: Any, *, error: str | None = None) -> str:
    if error:
        return "REJECTED"
    value = str(status or "").strip().replace(" ", "").upper()
    mapping = {
        "PENDINGSUBMIT": "PendingSubmit",
        "PRESUBMITTED": "PreSubmitted",
        "SUBMITTED": "Submitted",
        "PARTIALLYFILLED": "PartiallyFilled",
        "FILLED": "Filled",
        "CANCELLED": "Cancelled",
        "APICANCELLED": "Cancelled",
        "INACTIVE": "Inactive",
        "REJECTED": "Rejected",
    }
    return mapping.get(value, str(status or "Unknown"))


def is_active_status(status: Any) -> bool:
    return str(status or "").replace(" ", "").replace("_", "").upper() in {
        state.replace("_", "") for state in ACTIVE_BROKER_STATUSES
    }


def is_final_status(status: Any) -> bool:
    return str(status or "").replace(" ", "").replace("_", "").upper() in {
        state.replace("_", "") for state in FINAL_BROKER_STATUSES
    }


def default_store() -> dict[str, Any]:
    return {"bot": cfg.BOT_NAME, "updated_at_utc": utc_timestamp(), "orders": []}


def load_store(path=None) -> dict[str, Any]:
    path = path or cfg.AUTOMATED_ORDERS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_store()
    if not isinstance(data, dict):
        return default_store()
    data.setdefault("bot", cfg.BOT_NAME)
    data.setdefault("orders", [])
    return data


def save_store(store: dict[str, Any], path=None) -> None:
    path = path or cfg.AUTOMATED_ORDERS_FILE
    payload = deepcopy(store)
    payload["bot"] = cfg.BOT_NAME
    payload["updated_at_utc"] = utc_timestamp()
    atomic_write_json(path, payload)


def order_identity(intent: dict[str, Any]) -> str:
    payload = {
        "symbol": canonical_symbol(intent.get("symbol")),
        "side": str(intent.get("side") or "").upper(),
        "order_type": str(intent.get("order_type") or "").upper(),
        "limit_price": intent.get("limit_price"),
        "signal_date": str(intent.get("signal_date") or ""),
        "configuration_sha256": str(intent.get("configuration_sha256") or ""),
        "strategy_version": str(intent.get("strategy_version") or ""),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def find_order(store: dict[str, Any], order_key: str) -> dict[str, Any] | None:
    for order in store.get("orders", []) or []:
        if order.get("order_key") == order_key:
            return order
    return None


def logical_order_match(order: dict[str, Any], intent: dict[str, Any]) -> bool:
    return (
        canonical_symbol(order.get("symbol")) == canonical_symbol(intent.get("symbol"))
        and str(order.get("side") or "").upper() == str(intent.get("side") or "").upper()
        and str(order.get("order_type") or "").upper() == str(intent.get("order_type") or "").upper()
        and str(order.get("signal_date") or "") == str(intent.get("signal_date") or "")
        and str(order.get("configuration_sha256") or "") == str(intent.get("configuration_sha256") or "")
        and str(order.get("strategy_version") or "") == str(intent.get("strategy_version") or "")
    )


def find_logical_order(store: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any] | None:
    for order in store.get("orders", []) or []:
        if logical_order_match(order, intent):
            return order
    return None


def same_signal_order(order: dict[str, Any], intent: dict[str, Any]) -> bool:
    return (
        canonical_symbol(order.get("symbol")) == canonical_symbol(intent.get("symbol"))
        and str(order.get("side") or "").upper() == str(intent.get("side") or "").upper()
        and str(order.get("signal_date") or "") == str(intent.get("signal_date") or "")
        and str(order.get("strategy_version") or "") == str(intent.get("strategy_version") or "")
    )


def upsert_order_intent(intent: dict[str, Any], *, broker_status: str, reason: str = "") -> dict[str, Any]:
    store = load_store()
    now = utc_timestamp()
    row = dict(intent)
    row["symbol"] = canonical_symbol(row.get("symbol"))
    row["side"] = str(row.get("side") or "").upper()
    row["order_key"] = order_identity(row)
    row.setdefault("ibkr_order_id", None)
    row.setdefault("perm_id", None)
    row.setdefault("submitted_at_utc", None)
    row.setdefault("filled_quantity", 0.0)
    row.setdefault("remaining_quantity", row.get("quantity"))
    row.setdefault("average_fill_price", None)
    row.setdefault("rejection_reason", "")
    row.setdefault("cancellation_reason", "")
    existing = find_order(store, row["order_key"]) or find_logical_order(store, row)
    if existing is None:
        row["created_at_utc"] = now
        row["updated_at_utc"] = now
        row["broker_status"] = broker_status
        row["status_history"] = [{"timestamp_utc": now, "broker_status": broker_status, "reason": reason}]
        store["orders"].append(row)
        save_store(store)
        return row

    existing.update({key: value for key, value in row.items() if value is not None})
    existing["updated_at_utc"] = now
    existing["broker_status"] = broker_status
    history = list(existing.get("status_history") or [])
    if not history or history[-1].get("broker_status") != broker_status or reason:
        history.append({"timestamp_utc": now, "broker_status": broker_status, "reason": reason})
    existing["status_history"] = history[-50:]
    save_store(store)
    return existing


def update_order_status(
    *,
    order_key: str,
    broker_status: str,
    ibkr_order_id: Any = None,
    perm_id: Any = None,
    filled_quantity: Any = None,
    remaining_quantity: Any = None,
    average_fill_price: Any = None,
    rejection_reason: str = "",
    cancellation_reason: str = "",
) -> dict[str, Any] | None:
    store = load_store()
    order = find_order(store, order_key)
    if order is None:
        return None
    now = utc_timestamp()
    order["broker_status"] = normalize_broker_status(broker_status)
    order["updated_at_utc"] = now
    if ibkr_order_id not in (None, ""):
        order["ibkr_order_id"] = ibkr_order_id
    if perm_id not in (None, ""):
        order["perm_id"] = perm_id
    if filled_quantity is not None:
        order["filled_quantity"] = _parse_float(filled_quantity)
    if remaining_quantity is not None:
        order["remaining_quantity"] = _parse_float(remaining_quantity)
    if average_fill_price not in (None, ""):
        order["average_fill_price"] = _parse_float(average_fill_price)
    if rejection_reason:
        order["rejection_reason"] = rejection_reason
    if cancellation_reason:
        order["cancellation_reason"] = cancellation_reason
    history = list(order.get("status_history") or [])
    history.append(
        {
            "timestamp_utc": now,
            "broker_status": order["broker_status"],
            "filled_quantity": order.get("filled_quantity"),
            "remaining_quantity": order.get("remaining_quantity"),
            "average_fill_price": order.get("average_fill_price"),
            "rejection_reason": rejection_reason,
            "cancellation_reason": cancellation_reason,
        }
    )
    order["status_history"] = history[-50:]
    save_store(store)
    return order


def find_duplicate(
    intent: dict[str, Any],
    *,
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    include_dry_run: bool = False,
) -> str:
    symbol = canonical_symbol(intent.get("symbol"))
    side = str(intent.get("side") or "").upper()
    for row in positions:
        if canonical_symbol(row.get("symbol")) == symbol and _parse_float(row.get("quantity") or row.get("position")) > 0:
            if side == "BUY":
                return "current_ibkr_position"
    for row in open_orders:
        row_symbol = canonical_symbol(row.get("symbol") or (row.get("contract") or {}).get("symbol"))
        row_side = str(row.get("action") or (row.get("order") or {}).get("action") or "").upper()
        row_status = row.get("status") or (row.get("orderStatus") or {}).get("status")
        if row_symbol == symbol and row_side == side and not is_final_status(row_status):
            return "current_ibkr_open_order"
    store = load_store()
    order_key = order_identity(intent)
    existing = find_order(store, order_key) or find_logical_order(store, intent)
    if existing:
        status = existing.get("broker_status")
        if include_dry_run and status == "NotTransmitted":
            return "persisted_dry_run_intent"
        if is_active_status(status) or str(status).upper() in {"FILLED", "PARTIALLYFILLED", "PARTIALLY_FILLED"}:
            return "persisted_automated_order"
    for order in store.get("orders", []) or []:
        if not same_signal_order(order, intent):
            continue
        status = order.get("broker_status")
        if include_dry_run and status == "NotTransmitted":
            return "persisted_dry_run_intent"
        if is_active_status(status) or str(status).upper() in {"FILLED", "PARTIALLYFILLED", "PARTIALLY_FILLED"}:
            return "persisted_automated_order_same_signal"
    return ""


def runtime_summary() -> dict[str, Any]:
    store = load_store()
    orders = list(store.get("orders") or [])
    active = [row for row in orders if is_active_status(row.get("broker_status"))]
    submitted = [row for row in orders if row.get("submitted_at_utc")]
    last_submission = max((str(row.get("submitted_at_utc")) for row in submitted if row.get("submitted_at_utc")), default="")
    return {
        "orders_count": len(orders),
        "open_automated_orders": len(active),
        "last_order_submission": last_submission or "none",
        "last_order_status": orders[-1].get("broker_status") if orders else "none",
    }
