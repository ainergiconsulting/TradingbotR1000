"""Rebuild R1000 runtime state from broker evidence."""

from __future__ import annotations

from typing import Any

from monitoring_io import utc_timestamp
from state_store import default_state, load_state, save_state
try:
    from .symbol_mapping import canonical_symbol
except ImportError:  # pragma: no cover - supports direct script execution.
    from symbol_mapping import canonical_symbol


def rebuild_state_from_broker(
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    previous_state = load_state()
    previous_positions = previous_state.get("active_positions") or {}
    state = default_state()
    state["rebuilt_at_utc"] = utc_timestamp()
    state["active_positions"] = {
        canonical_symbol(row["symbol"]): {
            "symbol": canonical_symbol(row["symbol"]),
            "quantity": float(row.get("quantity", 0) or 0),
            "average_cost": float(row.get("average_cost", 0) or row.get("avgCost", 0) or 0),
            "market_price": float(row.get("marketPrice", 0) or 0),
            "market_value": float(row.get("marketValue", 0) or 0),
            "unrealized_pnl": float(row.get("unrealizedPNL", 0) or 0),
            "filled_entry_date": row.get("filled_entry_date")
            or (previous_positions.get(canonical_symbol(row["symbol"])) or {}).get("filled_entry_date"),
            "holding_trading_days": int(
                row.get("holding_trading_days")
                or (previous_positions.get(canonical_symbol(row["symbol"])) or {}).get("holding_trading_days", 0)
                or 0
            ),
            "contract": row.get("contract") or {},
        }
        for row in positions
        if float(row.get("quantity", 0) or 0) > 0
    }
    state["pending_buy_orders"] = {
        canonical_symbol(row["symbol"]): {**row, "symbol": canonical_symbol(row["symbol"])}
        for row in open_orders
        if str(row.get("action", "")).upper() == "BUY"
    }
    state["daily_scans"] = previous_state.get("daily_scans", [])[-30:]
    state["selected_candidates"] = previous_state.get("selected_candidates", [])
    state["exit_signals"] = previous_state.get("exit_signals", [])
    state["order_plans"] = previous_state.get("order_plans", [])
    return state


def rebuild_and_save(positions: list[dict[str, Any]], open_orders: list[dict[str, Any]]) -> dict[str, Any]:
    state = rebuild_state_from_broker(positions, open_orders)
    save_state(state)
    return state
