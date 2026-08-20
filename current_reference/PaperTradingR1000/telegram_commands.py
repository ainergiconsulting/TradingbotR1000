"""Read-only Telegram command renderers for TradingbotR1000."""

from __future__ import annotations

import json

import config as cfg
from execution_history import load_latest_execution_history
from gateway_status import collect_system_health
from monitoring_core import collect_runtime_status, read_json
from reconciliation import reconcile_local_state


def render_status() -> str:
    status = collect_runtime_status()
    health = status.get("runtime_health", {})
    scan = status.get("scan_report", {})
    return "\n".join(
        [
            f"{cfg.BOT_NAME} status",
            f"Engine: {health.get('strategy_engine_state', 'not checked')}",
            f"Last scan: {scan.get('timestamp_utc', 'none')}",
            f"Selected: {len(scan.get('selected_candidates', []))}",
            f"Orders planned: {len(scan.get('order_plans', []))}",
        ]
    )


def render_health() -> str:
    return json.dumps(collect_system_health(write=False), indent=2, default=str)


def render_portfolio() -> str:
    broker_snapshot = read_json(cfg.BROKER_SNAPSHOT_FILE)
    broker_positions = broker_snapshot.get("positions", [])
    if broker_positions:
        return json.dumps(broker_positions, indent=2, default=str)
    state = read_json(cfg.STATE_FILE)
    positions = state.get("active_positions", {})
    if not positions:
        return "No active R1000 positions recorded locally."
    return json.dumps(positions, indent=2, default=str)


def render_orders() -> str:
    return json.dumps(read_json(cfg.ORDER_PLAN_FILE).get("order_plans", []), indent=2, default=str)


def render_scan() -> str:
    scan = read_json(cfg.SCAN_REPORT_FILE)
    return json.dumps(
        {
            "timestamp_utc": scan.get("timestamp_utc"),
            "available_slots": scan.get("available_slots"),
            "ranking_applied": scan.get("ranking_applied"),
            "selected_candidates": [row.get("symbol") for row in scan.get("selected_candidates", [])],
            "rejected_symbols": scan.get("rejected_symbols", []),
        },
        indent=2,
        default=str,
    )


def render_executions() -> str:
    return json.dumps(load_latest_execution_history(), indent=2, default=str)


def render_reconciliation() -> str:
    return json.dumps(reconcile_local_state(), indent=2, default=str)


COMMANDS = {
    "status": render_status,
    "health": render_health,
    "portfolio": render_portfolio,
    "orders": render_orders,
    "scan": render_scan,
    "executions": render_executions,
    "reconciliation": render_reconciliation,
}
