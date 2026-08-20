"""Machine-readable runtime health publishing."""

from __future__ import annotations

from typing import Any

import config as cfg
from monitoring_io import atomic_write_json, utc_timestamp


HEALTH_STARTING = "STARTING"
HEALTH_OK = "OK"
HEALTH_FAILED = "FAILED"
HEALTH_STOPPED = "STOPPED"
HEALTH_RESTART_REQUIRED = "RESTART_REQUIRED"


def build_runtime_health(
    *,
    strategy_engine_state: str,
    ibkr_state: str = "not_checked",
    message: str = "",
    order_engine_state: str = "not_checked",
    startup_reconciliation_state: str = "not_checked",
    trading_state: str = "",
    last_strategy_cycle_status: str = "",
    last_strategy_cycle_time_utc: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = utc_timestamp()
    payload = {
        "bot": cfg.BOT_NAME,
        "timestamp": timestamp,
        "timestamp_utc": timestamp,
        "strategy_engine_state": strategy_engine_state,
        "order_engine_state": order_engine_state,
        "startup_reconciliation_state": startup_reconciliation_state,
        "trading_state": trading_state,
        "ibkr_state": ibkr_state,
        "execute_orders": cfg.EXECUTE_ORDERS,
        "paper_trading_required": cfg.PAPER_TRADING_REQUIRED,
        "message": message,
        "last_strategy_cycle_status": last_strategy_cycle_status,
        "last_strategy_cycle_time_utc": last_strategy_cycle_time_utc,
    }
    if extra:
        payload["extra"] = extra
    return payload


def write_runtime_health(**kwargs: Any) -> dict[str, Any]:
    payload = build_runtime_health(**kwargs)
    atomic_write_json(cfg.RUNTIME_HEALTH_FILE, payload)
    return payload


def mark_stopped(message: str = "stopped") -> dict[str, Any]:
    return write_runtime_health(strategy_engine_state=HEALTH_STOPPED, message=message)
