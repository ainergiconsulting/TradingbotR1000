"""Read-only Telegram command renderers for TradingbotR1000."""

from __future__ import annotations

import json

import config as cfg
from execution_history import load_latest_execution_history
from gateway_status import collect_system_health
from investable_capital_control import evaluate
from live_account import calculate_operational_buy_budget, collect_live_account_context
from monitoring_core import collect_runtime_status, read_json
from reconciliation import reconcile_local_state


def render_status() -> str:
    status = collect_runtime_status()
    health = status.get("runtime_health", {})
    scan = status.get("scan_report", {})

    snapshot = collect_live_account_context(
        client_id=cfg.TELEGRAM_CLIENT_ID,
        readonly=True,
    )
    values = snapshot.get("account_values", {})
    net_liquidation = float(values.get("net_liquidation") or 0.0)
    capital_limit = evaluate(net_liquidation)
    capital_budget = calculate_operational_buy_budget(
        values,
        strategy_cap=float(capital_limit.get("effective_investable_capital") or 0.0),
    )

    return "\n".join(
        [
            f"{cfg.BOT_NAME} status",
            f"Engine: {health.get('strategy_engine_state', 'not checked')}",
            f"Last scan: {scan.get('timestamp_utc', 'none')}",
            f"Selected: {len(scan.get('selected_candidates', []))}",
            f"Orders planned: {len(scan.get('order_plans', []))}",
            f"Account equity (NLV): ${net_liquidation:,.2f}",
            f"IBKR available funds: ${capital_budget['ibkr_available_funds']:,.2f}",
            f"Safety margin: {capital_budget['capital_safety_margin_pct'] * 100:.2f}%",
            f"Operational buy budget: ${capital_budget['operational_buy_budget']:,.2f}",
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
    open_orders = snapshot.get("open_orders", [])

    net_liquidation = float(values.get("net_liquidation") or 0.0)
    cash = float(values.get("cash") or 0.0)
    available_funds = float(values.get("available_funds") or 0.0)
    buying_power = float(values.get("buying_power") or 0.0)
    capital_limit = evaluate(net_liquidation)
    capital_budget = calculate_operational_buy_budget(
        values,
        strategy_cap=float(capital_limit.get("effective_investable_capital") or 0.0),
    )

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
        f"Account equity (NLV): ${net_liquidation:,.2f}",
        f"Cash: ${cash:,.2f}",
        f"IBKR available funds: ${available_funds:,.2f}",
        f"Look-ahead available: ${capital_budget['ibkr_lookahead_available_funds']:,.2f}",
        f"Safety margin: {capital_budget['capital_safety_margin_pct'] * 100:.2f}%",
        f"Operational buy budget: ${capital_budget['operational_buy_budget']:,.2f}",
        f"Buying power (informational): ${buying_power:,.2f}",
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

    pending_orders = []
    for row in open_orders:
        status = str(row.get("status") or row.get("orderStatus", {}).get("status") or "UNKNOWN")
        quantity = float(row.get("quantity") or row.get("order", {}).get("totalQuantity") or 0.0)
        filled_raw = row.get("filled")
        if filled_raw in (None, ""):
            filled_raw = row.get("orderStatus", {}).get("filled")
        remaining_raw = row.get("remaining")
        if remaining_raw in (None, ""):
            remaining_raw = row.get("orderStatus", {}).get("remaining")
        filled = float(filled_raw or 0.0)
        remaining = float(remaining_raw) if remaining_raw not in (None, "") else max(0.0, quantity - filled)
        if remaining <= 0:
            continue
        pending_orders.append((row, status, quantity, filled, remaining))

    lines.extend(["", f"Pending orders: {len(pending_orders)}"])
    if pending_orders:
        for row, status, quantity, filled, remaining in pending_orders:
            symbol = str(row.get("symbol") or row.get("ibkrSymbol") or "UNKNOWN")
            action = str(row.get("action") or row.get("order", {}).get("action") or "")
            limit_raw = row.get("limit_price")
            if limit_raw in (None, ""):
                limit_raw = row.get("order", {}).get("lmtPrice")
            limit_price = float(limit_raw or 0.0)
            lines.extend(
                [
                    "",
                    f"{symbol} {action}".strip(),
                    f"Ordered: {quantity:g} @ ${limit_price:,.2f}",
                    f"Filled: {filled:g}",
                    f"Pending: {remaining:g}",
                    f"IBKR status: {status}",
                ]
            )
    else:
        lines.append("No pending broker orders.")

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
