"""Read-only live IBKR API evidence helpers for operational status.

These helpers collect account summary, positions, and open orders from an
already-connected IBKR API session. They do not save files, submit orders,
modify orders, cancel orders, or change strategy state.
"""

from __future__ import annotations

from typing import Any

try:
    from .ibkr_utils import ensure_current_event_loop
    from .symbol_mapping import canonical_symbol_from_ibkr
except ImportError:  # pragma: no cover - direct script execution support.
    from ibkr_utils import ensure_current_event_loop
    from symbol_mapping import canonical_symbol_from_ibkr

try:
    ensure_current_event_loop()
    from ib_insync import IB
except Exception:  # pragma: no cover - depends on local runtime environment.
    IB = object


def simple_contract(contract: Any) -> dict[str, Any]:
    raw_symbol = str(getattr(contract, "symbol", "") or "")
    return {
        "conId": str(getattr(contract, "conId", "") or ""),
        "symbol": canonical_symbol_from_ibkr(raw_symbol),
        "ibkrSymbol": raw_symbol,
        "secType": str(getattr(contract, "secType", "") or ""),
        "exchange": str(getattr(contract, "exchange", "") or ""),
        "primaryExchange": str(getattr(contract, "primaryExchange", "") or ""),
        "currency": str(getattr(contract, "currency", "") or ""),
        "localSymbol": str(getattr(contract, "localSymbol", "") or ""),
        "tradingClass": str(getattr(contract, "tradingClass", "") or ""),
    }


def _position_key(account: str, contract: Any) -> tuple[str, str, str, str, str]:
    return (
        str(account or ""),
        str(getattr(contract, "conId", "") or ""),
        str(getattr(contract, "symbol", "") or ""),
        str(getattr(contract, "currency", "") or ""),
        str(getattr(contract, "secType", "") or ""),
    )


def _simple_number(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def snapshot_account_summary(ib: IB) -> list[dict[str, Any]]:
    rows = []
    for item in ib.accountSummary():
        rows.append(
            {
                "account": str(getattr(item, "account", "") or ""),
                "tag": str(getattr(item, "tag", "") or ""),
                "value": str(getattr(item, "value", "") or ""),
                "currency": str(getattr(item, "currency", "") or ""),
                "modelCode": str(getattr(item, "modelCode", "") or ""),
            }
        )
    return rows


def snapshot_positions(ib: IB) -> list[dict[str, Any]]:
    portfolio_by_key = {}
    try:
        for item in ib.portfolio():
            contract = getattr(item, "contract", None)
            key = _position_key(getattr(item, "account", ""), contract)
            fallback_key = _position_key("", contract)
            details = {
                "symbol": canonical_symbol_from_ibkr(getattr(contract, "symbol", "")),
                "ibkrSymbol": str(getattr(contract, "symbol", "") or ""),
                "conId": str(getattr(contract, "conId", "") or ""),
                "currency": str(getattr(contract, "currency", "") or ""),
                "quantity": _simple_number(getattr(item, "position", "")),
                "averageCost": _simple_number(getattr(item, "averageCost", "")),
                "marketPrice": _simple_number(getattr(item, "marketPrice", "")),
                "marketValue": _simple_number(getattr(item, "marketValue", "")),
                "unrealizedPNL": _simple_number(getattr(item, "unrealizedPNL", "")),
                "realizedPNL": _simple_number(getattr(item, "realizedPNL", "")),
                "exchange": str(getattr(contract, "exchange", "") or ""),
                "primaryExchange": str(getattr(contract, "primaryExchange", "") or ""),
            }
            portfolio_by_key[key] = details
            portfolio_by_key.setdefault(fallback_key, details)
    except Exception:
        portfolio_by_key = {}

    rows = []
    for position in ib.positions():
        contract = getattr(position, "contract", None)
        account = str(getattr(position, "account", "") or "")
        portfolio_details = portfolio_by_key.get(
            _position_key(account, contract),
            portfolio_by_key.get(_position_key("", contract), {}),
        )
        rows.append(
            {
                "account": account,
                "position": str(getattr(position, "position", "") or ""),
                "quantity": portfolio_details.get("quantity") or str(getattr(position, "position", "") or ""),
                "avgCost": str(getattr(position, "avgCost", "") or ""),
                "averageCost": portfolio_details.get("averageCost")
                or str(getattr(position, "avgCost", "") or ""),
                "marketPrice": portfolio_details.get("marketPrice", ""),
                "marketValue": portfolio_details.get("marketValue", ""),
                "unrealizedPNL": portfolio_details.get("unrealizedPNL", ""),
                "realizedPNL": portfolio_details.get("realizedPNL", ""),
                "symbol": portfolio_details.get("symbol") or canonical_symbol_from_ibkr(getattr(contract, "symbol", "")),
                "ibkrSymbol": portfolio_details.get("ibkrSymbol") or str(getattr(contract, "symbol", "") or ""),
                "conId": portfolio_details.get("conId") or str(getattr(contract, "conId", "") or ""),
                "currency": portfolio_details.get("currency") or str(getattr(contract, "currency", "") or ""),
                "exchange": portfolio_details.get("exchange") or str(getattr(contract, "exchange", "") or ""),
                "primaryExchange": portfolio_details.get("primaryExchange")
                or str(getattr(contract, "primaryExchange", "") or ""),
                "contract": simple_contract(contract),
            }
        )
    return rows


def snapshot_open_orders(ib: IB) -> list[dict[str, Any]]:
    rows = []
    try:
        ib.reqAllOpenOrders()
    except Exception:
        pass

    try:
        ib.reqOpenOrders()
    except Exception:
        pass

    for trade in ib.openTrades():
        order = getattr(trade, "order", None)
        status = getattr(trade, "orderStatus", None)
        contract = getattr(trade, "contract", None)
        simple = simple_contract(contract)
        rows.append(
            {
                "symbol": simple.get("symbol", ""),
                "ibkrSymbol": simple.get("ibkrSymbol", ""),
                "action": str(getattr(order, "action", "") or ""),
                "quantity": str(getattr(order, "totalQuantity", "") or ""),
                "limit_price": str(getattr(order, "lmtPrice", "") or ""),
                "status": str(getattr(status, "status", "") or ""),
                "filled": str(getattr(status, "filled", "") or ""),
                "remaining": str(getattr(status, "remaining", "") or ""),
                "contract": simple,
                "order": {
                    "orderId": str(getattr(order, "orderId", "") or ""),
                    "permId": str(getattr(order, "permId", "") or ""),
                    "clientId": str(getattr(order, "clientId", "") or ""),
                    "action": str(getattr(order, "action", "") or ""),
                    "orderType": str(getattr(order, "orderType", "") or ""),
                    "totalQuantity": str(getattr(order, "totalQuantity", "") or ""),
                    "lmtPrice": str(getattr(order, "lmtPrice", "") or ""),
                    "auxPrice": str(getattr(order, "auxPrice", "") or ""),
                },
                "orderStatus": {
                    "status": str(getattr(status, "status", "") or ""),
                    "filled": str(getattr(status, "filled", "") or ""),
                    "remaining": str(getattr(status, "remaining", "") or ""),
                    "avgFillPrice": str(getattr(status, "avgFillPrice", "") or ""),
                },
            }
        )
    return rows


def snapshot_executions(ib: IB) -> list[dict[str, Any]]:
    rows = []
    try:
        ib.reqExecutions()
    except Exception:
        pass
    for fill in getattr(ib, "fills", lambda: [])() or []:
        contract = getattr(fill, "contract", None)
        execution = getattr(fill, "execution", None)
        commission = getattr(fill, "commissionReport", None)
        simple = simple_contract(contract)
        rows.append(
            {
                "symbol": simple.get("symbol", ""),
                "ibkrSymbol": simple.get("ibkrSymbol", ""),
                "contract": simple,
                "execution": {
                    "execId": str(getattr(execution, "execId", "") or ""),
                    "orderId": str(getattr(execution, "orderId", "") or ""),
                    "permId": str(getattr(execution, "permId", "") or ""),
                    "clientId": str(getattr(execution, "clientId", "") or ""),
                    "side": str(getattr(execution, "side", "") or ""),
                    "shares": str(getattr(execution, "shares", "") or ""),
                    "price": str(getattr(execution, "price", "") or ""),
                    "time": str(getattr(execution, "time", "") or ""),
                    "acctNumber": str(getattr(execution, "acctNumber", "") or ""),
                },
                "commission": {
                    "commission": str(getattr(commission, "commission", "") or ""),
                    "currency": str(getattr(commission, "currency", "") or ""),
                    "realizedPNL": str(getattr(commission, "realizedPNL", "") or ""),
                },
            }
        )
    return rows
