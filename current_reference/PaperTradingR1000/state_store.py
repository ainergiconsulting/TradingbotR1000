"""Atomic-ish JSON state store for TradingbotR1000 runtime state."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import config as cfg
from logger_utils import log
from monitoring_io import atomic_write_json
try:
    from .symbol_mapping import canonical_symbol
except ImportError:  # pragma: no cover - supports direct script execution.
    from symbol_mapping import canonical_symbol


STATE_VERSION = 1


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_state() -> dict[str, Any]:
    return {
        "state_version": STATE_VERSION,
        "bot": cfg.BOT_NAME,
        "created_at_utc": utc_timestamp(),
        "updated_at_utc": utc_timestamp(),
        "active_positions": {},
        "pending_buy_orders": {},
        "daily_scans": [],
        "selected_candidates": [],
        "exit_signals": [],
        "order_plans": [],
        "reconciliation": {},
    }


def load_state(path: Path = cfg.STATE_FILE) -> dict[str, Any]:
    if not path.exists():
        return default_state()
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"state file is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"state file must contain an object: {path}")
    state = default_state()
    state.update(data)
    return state


def save_state(state: dict[str, Any], path: Path = cfg.STATE_FILE) -> None:
    payload = deepcopy(state)
    payload["state_version"] = STATE_VERSION
    payload["bot"] = cfg.BOT_NAME
    payload["updated_at_utc"] = utc_timestamp()
    atomic_write_json(path, payload)


def record_daily_scan(scan: dict[str, Any], path: Path = cfg.STATE_FILE) -> dict[str, Any]:
    state = load_state(path)
    scans = list(state.get("daily_scans") or [])
    scans.append(scan)
    state["daily_scans"] = scans[-30:]
    state["selected_candidates"] = scan.get("selected_candidates", [])
    state["order_plans"] = scan.get("order_plans", [])
    save_state(state, path)
    log("daily scan recorded", extra={"selected": len(state["selected_candidates"])})
    return state


def set_pending_buy_orders(orders: dict[str, Any], path: Path = cfg.STATE_FILE) -> dict[str, Any]:
    state = load_state(path)
    canonical_orders: dict[str, Any] = {}
    for key, value in orders.items():
        symbol = canonical_symbol(value.get("symbol") if isinstance(value, dict) else key)
        if not symbol:
            continue
        if isinstance(value, dict):
            row = dict(value)
            row["symbol"] = symbol
            canonical_orders[symbol] = row
        else:
            canonical_orders[symbol] = value
    state["pending_buy_orders"] = canonical_orders
    save_state(state, path)
    return state


def active_position_count(state: dict[str, Any]) -> int:
    return len(active_position_symbols(state))


def active_position_symbols(state: dict[str, Any]) -> set[str]:
    positions = state.get("active_positions") or {}
    return {
        canonical_symbol(value.get("symbol") if isinstance(value, dict) and value.get("symbol") else symbol)
        for symbol, value in positions.items()
        if float(value.get("quantity", 0) or 0) > 0
    }


def pending_buy_count(state: dict[str, Any]) -> int:
    return len(pending_buy_symbols(state))


def pending_buy_symbols(state: dict[str, Any]) -> set[str]:
    pending = state.get("pending_buy_orders") or {}
    symbols = set()
    for key, value in pending.items():
        symbol = value.get("symbol") if isinstance(value, dict) else key
        canonical = canonical_symbol(symbol or key)
        if canonical:
            symbols.add(canonical)
    return symbols


def reserved_position_symbols(state: dict[str, Any]) -> set[str]:
    return active_position_symbols(state) | pending_buy_symbols(state)
