"""Read-only Telegram command renderers for TradingbotR1000."""

from __future__ import annotations

import json

import config as cfg
from execution_history import load_latest_execution_history
from gateway_status import collect_system_health
from live_account import collect_live_account_context
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
    health = collect_system_health()
    return "\n".join(
        [
            f"{cfg.BOT_NAME} health",
            f"Gateway: {health.get('gateway_process_status', 'UNKNOWN')}",
            f"API socket: {health.get('api_socket_status', 'UNKNOWN')}",
            f"Live API: {health.get('live_api_status', 'UNKNOWN')}",
            f"Market: {health.get('market_status', 'UNKNOWN')}",
            f"Liquid hours: {health.get('liquid_hours_status', 'UNKNOWN')}",
            f"Runtime: {health.get('runtime_process', 'UNKNOWN')}",
            f"Heartbeat: {health.get('last_heartbeat_age', 'unknown')}",
            f"Reconciliation: {health.get('last_reconciliation_result', 'UNKNOWN')}",
            f"Trading enabled: {health.get('trading_enabled', False)}",
            f"Reason: {health.get('reason_trading_disabled', '') or 'none'}",
        ]
    )


def render_portfolio() -> str:
    snapshot = collect_live_account_context(
        client_id=cfg.TELEGRAM_CLIENT_ID,
        readonly=True,
    )

    values = snapshot.get("account_values", {})
    positions = snapshot.get("positions", [])

    net_liquidation = float(values.get("net_liquidation") or 0.0)
    cash = float(values.get("cash") or 0.0)
    available_funds = float(values.get("available_funds") or 0.0)
    buying_power = float(values.get("buying_power") or 0.0)

    total_invested = 0.0
    position_lines = []

    for row in positions:
        symbol = str(row.get("symbol") or "")
        quantity = float(row.get("quantity") or 0.0)
        average_cost = float(row.get("averageCost") or 0.0)
        market_price = float(row.get("marketPrice") or 0.0)
        market_value = float(row.get("marketValue") or 0.0)
        unrealized_pnl = float(row.get("unrealizedPNL") or 0.0)

        total_invested += market_value
        weight = (
            market_value / net_liquidation * 100.0
            if net_liquidation > 0
            else 0.0
        )

        position_lines.extend(
            [
                "",
                symbol or "UNKNOWN",
                f"Qty: {quantity:g}",
                f"Avg: ${average_cost:,.2f}",
                f"Price: ${market_price:,.2f}",
                f"Value: ${market_value:,.2f}",
                f"Unrealized P&L: ${unrealized_pnl:,.2f}",
                f"Weight: {weight:.2f}%",
            ]
        )

    cash_weight = (
        cash / net_liquidation * 100.0
        if net_liquidation > 0
        else 0.0
    )

    lines = [
        f"{cfg.BOT_NAME} Portfolio",
        f"Account mode: {snapshot.get('account_mode', 'UNKNOWN')}",
        f"Timestamp: {snapshot.get('timestamp_utc', '')}",
        "",
        f"Net liquidation: ${net_liquidation:,.2f}",
        f"Cash: ${cash:,.2f}",
        f"Available funds: ${available_funds:,.2f}",
        f"Buying power: ${buying_power:,.2f}",
        "",
        f"Positions: {len(positions)}",
        f"Invested: ${total_invested:,.2f}",
        f"Cash weight: {cash_weight:.2f}%",
    ]

    if positions:
        lines.extend(position_lines)
    else:
        lines.append("")
        lines.append("No open broker positions.")

    return "\n".join(lines)


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
