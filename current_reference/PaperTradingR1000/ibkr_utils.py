"""IBKR integration helpers adapted for TradingbotR1000.

This module keeps broker connectivity separate from strategy rules. Market data
request parameters are implementation settings supplied by callers.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterator, Sequence
from zoneinfo import ZoneInfo

import config as cfg
from logger_utils import log
try:
    from .symbol_mapping import (
        canonical_symbol,
        canonical_symbol_from_ibkr,
        expected_ibkr_primary_exchange,
        ibkr_symbol,
    )
except ImportError:  # pragma: no cover - supports direct script execution.
    from symbol_mapping import (
        canonical_symbol,
        canonical_symbol_from_ibkr,
        expected_ibkr_primary_exchange,
        ibkr_symbol,
    )


def ensure_current_event_loop() -> None:
    """Create a main-thread asyncio loop when Python does not provide one.

    Python 3.14 no longer guarantees that ``asyncio.get_event_loop()`` creates
    a default loop. ``ib_insync`` imports ``eventkit``, which still expects one.
    """

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("current event loop is closed")
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


ensure_current_event_loop()


try:
    from ib_insync import IB, Stock, Contract, MarketOrder
except ImportError:  # pragma: no cover - exercised when dependency is absent.
    IB = None
    Stock = None
    MarketOrder = None
    Contract = Any


class IBKRDependencyError(RuntimeError):
    pass


MARKET_HOURS_TIME_UNAVAILABLE_REASON = "Market-hours status unavailable: trusted time source unavailable"
IBKR_BLOCKING_REQUEST_TIMEOUT_SECONDS = 3.0
_CONTRACT_DETAILS_CACHE: dict[str, Any] = {}


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    date: str
    close: float
    rsi2: float | None = None


def require_ib_insync() -> None:
    if IB is None or Stock is None:
        raise IBKRDependencyError("ib_insync is not installed")


def connect(client_id: int | None = None, readonly: bool = True) -> Any:
    require_ib_insync()
    ensure_current_event_loop()
    ib = IB()
    ib.connect(cfg.HOST, cfg.PORT, clientId=client_id or cfg.CLIENT_ID, readonly=readonly)
    return ib


def set_ibkr_request_timeout(ib: Any, timeout_seconds: float = IBKR_BLOCKING_REQUEST_TIMEOUT_SECONDS) -> None:
    try:
        current = float(getattr(ib, "RequestTimeout", 0) or 0)
        timeout = float(timeout_seconds)
        if current <= 0 or current > timeout:
            ib.RequestTimeout = timeout
    except Exception:
        pass


@contextmanager
def ibkr_request_timeout(ib: Any, timeout_seconds: float = IBKR_BLOCKING_REQUEST_TIMEOUT_SECONDS) -> Iterator[None]:
    previous = getattr(ib, "RequestTimeout", 0)
    try:
        try:
            current = float(getattr(ib, "RequestTimeout", 0) or 0)
            timeout = float(timeout_seconds)
            if current <= 0 or current > timeout:
                ib.RequestTimeout = timeout
        except Exception:
            pass
        yield
    finally:
        try:
            ib.RequestTimeout = previous
        except Exception:
            pass


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if math.isnan(number) or number <= 0:
            return None
        return number
    except Exception:
        return None


def _contract_key(contract: Any) -> str:
    con_id = getattr(contract, "conId", None)
    if con_id:
        return f"CONID_{con_id}"
    return "_".join(
        [
            str(getattr(contract, "symbol", "") or ""),
            str(getattr(contract, "exchange", "") or ""),
            str(getattr(contract, "currency", "") or ""),
        ]
    )


def normalize_ib_timezone(timezone_id: str | None) -> str | None:
    mapping = {
        "EST": "America/New_York",
        "EDT": "America/New_York",
        "CST": "America/Chicago",
        "MST": "America/Denver",
        "PST": "America/Los_Angeles",
        "MET": "Europe/Amsterdam",
        "CET": "Europe/Paris",
        "GB-Eire": "Europe/London",
        "GMT": "Europe/London",
        "UTC": "UTC",
    }
    if timezone_id is None:
        return None
    return mapping.get(timezone_id, timezone_id)


def get_zoneinfo(timezone_id: str | None) -> ZoneInfo | None:
    try:
        normalized = normalize_ib_timezone(timezone_id)
        return ZoneInfo(normalized) if normalized else None
    except Exception:
        return None


def parse_ibkr_hours_segment(segment: str | None):
    if not segment or "CLOSED" in segment or "-" not in segment:
        return None
    try:
        start_txt, end_txt = str(segment).split("-")
        start_dt = datetime.strptime(start_txt, "%Y%m%d:%H%M")
        end_dt = datetime.strptime(end_txt, "%Y%m%d:%H%M")
        return start_dt, end_dt
    except Exception:
        return None


def _normalize_ibkr_time(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_ibkr_server_time(ib: Any) -> datetime | None:
    try:
        with ibkr_request_timeout(ib):
            return _normalize_ibkr_time(ib.reqCurrentTime())
    except Exception as exc:
        log("IBKR server time unavailable", level="WARNING", extra={"error": repr(exc)})
        return None


def get_contract_details(ib: Any, contract: Any) -> Any | None:
    key = _contract_key(contract)
    if key in _CONTRACT_DETAILS_CACHE:
        return _CONTRACT_DETAILS_CACHE[key]
    try:
        with ibkr_request_timeout(ib):
            details_list = ib.reqContractDetails(contract)
        if not details_list:
            log("no contract details returned by IBKR", level="WARNING", extra={"symbol": getattr(contract, "symbol", "")})
            return None
        details = details_list[0]
        _CONTRACT_DETAILS_CACHE[key] = details
        return details
    except Exception as exc:
        log("reqContractDetails failed", level="WARNING", extra={"symbol": getattr(contract, "symbol", ""), "error": repr(exc)})
        return None


def stock_contract(
    symbol: str,
    currency: str = "USD",
    exchange: str = "SMART",
    primary_exchange: str | None = None,
) -> Any:
    require_ib_insync()
    contract = Stock(ibkr_symbol(symbol), exchange, currency)
    normalized_primary = expected_ibkr_primary_exchange(primary_exchange)
    if normalized_primary:
        contract.primaryExchange = normalized_primary
    return contract


def market_order(action: str, quantity: float) -> Any:
    require_ib_insync()
    return MarketOrder(action.upper(), quantity)


def contract_to_state_dict(contract: Any) -> dict[str, Any]:
    raw_symbol = str(getattr(contract, "symbol", "") or "")
    return {
        "symbol": canonical_symbol_from_ibkr(raw_symbol),
        "ibkr_symbol": raw_symbol,
        "secType": str(getattr(contract, "secType", "") or ""),
        "exchange": str(getattr(contract, "exchange", "") or ""),
        "primaryExchange": str(getattr(contract, "primaryExchange", "") or ""),
        "currency": str(getattr(contract, "currency", "") or ""),
        "conId": str(getattr(contract, "conId", "") or ""),
        "localSymbol": str(getattr(contract, "localSymbol", "") or ""),
    }


def get_account_value(account_summary: Sequence[Any], tag: str = "NetLiquidation") -> float:
    for item in account_summary:
        if str(getattr(item, "tag", "") or "") == tag:
            value = str(getattr(item, "value", "") or "").replace(",", "")
            try:
                return float(value)
            except ValueError:
                return 0.0
    return 0.0


def read_positions(ib: Any) -> list[dict[str, Any]]:
    rows = []
    for position in ib.positions():
        contract = getattr(position, "contract", None)
        rows.append(
            {
                "symbol": canonical_symbol_from_ibkr(getattr(contract, "symbol", "")),
                "quantity": float(getattr(position, "position", 0) or 0),
                "average_cost": float(getattr(position, "avgCost", 0) or 0),
                "account": str(getattr(position, "account", "") or ""),
                "contract": contract_to_state_dict(contract),
            }
        )
    return rows


def read_open_orders(ib: Any) -> list[dict[str, Any]]:
    rows = []
    try:
        ib.reqAllOpenOrders()
    except Exception as exc:
        log("open-order refresh failed", level="WARNING", extra={"error": repr(exc)})
    for trade in ib.openTrades():
        order = getattr(trade, "order", None)
        contract = getattr(trade, "contract", None)
        rows.append(
            {
                "symbol": canonical_symbol_from_ibkr(getattr(contract, "symbol", "")),
                "action": str(getattr(order, "action", "") or ""),
                "quantity": float(getattr(order, "totalQuantity", 0) or 0),
                "limit_price": float(getattr(order, "lmtPrice", 0) or 0),
                "status": str(getattr(getattr(trade, "orderStatus", None), "status", "") or ""),
            }
        )
    return rows


def fetch_daily_closes(
    ib: Any,
    symbol: str,
    *,
    duration: str = "260 D",
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
) -> list[float]:
    contract = stock_contract(symbol)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow=what_to_show,
        useRTH=use_rth,
        formatDate=1,
    )
    return [float(bar.close) for bar in bars]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
