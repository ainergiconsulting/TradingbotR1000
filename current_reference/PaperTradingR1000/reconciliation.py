"""R1000 reconciliation summary from local order-plan and broker evidence files."""

from __future__ import annotations

import json
from typing import Any

import config as cfg
from automated_order_store import load_store, normalize_broker_status, save_store
from monitoring_core import read_json
from monitoring_io import atomic_write_json, utc_timestamp
from startup_rebuild import rebuild_and_save
try:
    from .symbol_mapping import canonical_symbol
except ImportError:  # pragma: no cover - supports direct script execution.
    from symbol_mapping import canonical_symbol


def reconcile_local_state(
    order_plan: dict[str, Any] | None = None,
    broker_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    order_plan = order_plan or read_json(cfg.ORDER_PLAN_FILE)
    broker_snapshot = broker_snapshot or read_json(cfg.BROKER_SNAPSHOT_FILE)
    rebuilt_state = rebuild_and_save(
        list(broker_snapshot.get("positions", []) or []),
        list(broker_snapshot.get("open_orders", []) or []),
    )
    order_updates = reconcile_automated_orders(broker_snapshot)
    planned_symbols = {canonical_symbol(row.get("symbol")) for row in order_plan.get("order_plans", [])}
    open_order_symbols = {
        canonical_symbol(row.get("symbol") or row.get("contract", {}).get("symbol"))
        for row in broker_snapshot.get("open_orders", [])
    }
    planned_symbols.discard("")
    open_order_symbols.discard("")
    timestamp = utc_timestamp()
    result = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": timestamp,
        "generated_at_utc": timestamp,
        "planned_order_count": len(planned_symbols),
        "broker_open_order_count": len(open_order_symbols),
        "broker_position_count": len(broker_snapshot.get("positions", []) or []),
        "broker_execution_count": len(broker_snapshot.get("executions", []) or []),
        "automated_order_updates": order_updates,
        "active_position_count": len(rebuilt_state.get("active_positions", {}) or {}),
        "pending_buy_order_count": len(rebuilt_state.get("pending_buy_orders", {}) or {}),
        "planned_without_open_order": sorted(symbol for symbol in planned_symbols - open_order_symbols if symbol),
        "open_order_without_plan": sorted(symbol for symbol in open_order_symbols - planned_symbols if symbol),
        "status": "RECONCILED",
    }
    atomic_write_json(cfg.RECONCILIATION_REPORT_FILE, result)
    return result


def _order_match(order: dict[str, Any], broker_order_id: str, broker_perm_id: str) -> bool:
    if broker_perm_id and str(order.get("perm_id") or "") == broker_perm_id:
        return True
    if broker_order_id and str(order.get("ibkr_order_id") or "") == broker_order_id:
        return True
    return False


def reconcile_automated_orders(broker_snapshot: dict[str, Any]) -> dict[str, int]:
    store = load_store()
    orders = list(store.get("orders") or [])
    updates = {"open_order_updates": 0, "execution_updates": 0}
    for open_order in broker_snapshot.get("open_orders", []) or []:
        order_payload = open_order.get("order") or {}
        status_payload = open_order.get("orderStatus") or {}
        order_id = str(order_payload.get("orderId") or "")
        perm_id = str(order_payload.get("permId") or "")
        for order in orders:
            if not _order_match(order, order_id, perm_id):
                continue
            order["broker_status"] = normalize_broker_status(status_payload.get("status"))
            order["filled_quantity"] = float(status_payload.get("filled") or 0)
            order["remaining_quantity"] = float(status_payload.get("remaining") or 0)
            order["average_fill_price"] = float(status_payload.get("avgFillPrice") or 0)
            order["updated_at_utc"] = utc_timestamp()
            updates["open_order_updates"] += 1
    for fill in broker_snapshot.get("executions", []) or []:
        execution = fill.get("execution") or {}
        order_id = str(execution.get("orderId") or "")
        perm_id = str(execution.get("permId") or "")
        shares = float(execution.get("shares") or 0)
        price = float(execution.get("price") or 0)
        for order in orders:
            if not _order_match(order, order_id, perm_id):
                continue
            previous_filled = float(order.get("filled_quantity") or 0)
            filled = max(previous_filled, shares)
            order["filled_quantity"] = filled
            order["remaining_quantity"] = max(0.0, float(order.get("quantity") or 0) - filled)
            order["average_fill_price"] = price or order.get("average_fill_price")
            order["broker_status"] = "Filled" if order["remaining_quantity"] <= 0 else "PartiallyFilled"
            order["updated_at_utc"] = utc_timestamp()
            updates["execution_updates"] += 1
    store["orders"] = orders
    save_store(store)
    return updates


def main() -> int:
    print(json.dumps(reconcile_local_state(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
