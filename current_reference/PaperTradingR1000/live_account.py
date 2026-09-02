"""Live IBKR PAPER account context for automated R1000 runtime sizing."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

import config as cfg
from ibkr_utils import connect
from monitoring_io import atomic_write_json, utc_timestamp
from operational_api_snapshot import snapshot_account_summary, snapshot_executions, snapshot_open_orders, snapshot_positions


class LiveAccountError(RuntimeError):
    """Raised when live broker account evidence is unavailable or unsafe."""


ACCOUNT_TAGS = {
    "NetLiquidation": "net_liquidation",
    "TotalCashValue": "cash",
    "CashBalance": "cash",
    "AvailableFunds": "available_funds",
    "LookAheadAvailableFunds": "lookahead_available_funds",
    "AccruedCash": "accrued_cash",
    "BuyingPower": "buying_power",
    "GrossPositionValue": "gross_position_value",
}


def _parse_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _account_mode(accounts: list[str]) -> str:
    if accounts and all(str(account).upper().startswith("DU") for account in accounts):
        return "PAPER"
    return "UNKNOWN"


def _account_values(account_summary: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in account_summary:
        target = ACCOUNT_TAGS.get(str(row.get("tag", "")))
        if not target:
            continue
        number = _parse_float(row.get("value"))
        currency = str(row.get("currency", "") or "").upper()
        if number is None:
            continue
        if currency and currency not in cfg.ALLOWED_CURRENCIES:
            continue
        values.setdefault(target, number)
    return values


def calculate_operational_buy_budget(
    account_values: dict[str, Any],
    *,
    strategy_cap: float | None = None,
    safety_margin_pct: float | None = None,
) -> dict[str, float]:
    """Return the no-leverage broker-authoritative BUY budget.

    Current IBKR AvailableFunds is authoritative. LookAheadAvailableFunds is a
    conservative forward-looking cap when present. NLV and BuyingPower are
    intentionally excluded from spendable-capital calculation.
    """
    available = _parse_float(account_values.get("available_funds"))
    lookahead = _parse_float(account_values.get("lookahead_available_funds"))
    if available is None or available < 0:
        raise LiveAccountError("available_funds_missing_or_invalid")
    broker_available = min(available, lookahead) if lookahead is not None and lookahead >= 0 else available
    margin_pct = cfg.CAPITAL_SAFETY_MARGIN_PCT if safety_margin_pct is None else float(safety_margin_pct)
    if not 0 <= margin_pct < 1:
        raise LiveAccountError("capital_safety_margin_pct_invalid")
    capped = broker_available if strategy_cap is None else min(broker_available, max(0.0, float(strategy_cap)))
    margin_value = capped * margin_pct
    return {
        "ibkr_available_funds": available,
        "ibkr_lookahead_available_funds": lookahead if lookahead is not None else available,
        "broker_available_capital": broker_available,
        "strategy_cap": capped,
        "capital_safety_margin_pct": margin_pct,
        "capital_safety_margin_value": margin_value,
        "operational_buy_budget": max(0.0, capped - margin_value),
    }


def _age_seconds(timestamp_utc: str, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    try:
        timestamp = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    except Exception as exc:
        raise LiveAccountError("live_account_timestamp_invalid") from exc
    return max(0.0, (now - timestamp).total_seconds())


def validate_live_account_snapshot(snapshot: dict[str, Any], *, max_age_seconds: int | None = None) -> dict[str, Any]:
    max_age = cfg.LIVE_ACCOUNT_MAX_AGE_SECONDS if max_age_seconds is None else int(max_age_seconds)
    timestamp = str(snapshot.get("timestamp_utc") or "")
    age = _age_seconds(timestamp)
    if age > max_age:
        raise LiveAccountError(f"live_account_snapshot_stale:{age:.1f}s")
    if cfg.PAPER_TRADING_REQUIRED and snapshot.get("account_mode") != "PAPER":
        raise LiveAccountError("paper_account_not_confirmed")
    values = snapshot.get("account_values") or {}
    required = ("net_liquidation", "cash", "available_funds")
    missing = [key for key in required if _parse_float(values.get(key)) is None]
    if missing:
        raise LiveAccountError("live_account_values_missing:" + ",".join(missing))
    if float(values["net_liquidation"]) <= 0:
        raise LiveAccountError("net_liquidation_not_positive")
    return snapshot


def collect_live_account_context(*, client_id: int | None = None, readonly: bool = True) -> dict[str, Any]:
    """Collect fresh broker-authoritative account, position, and open-order evidence."""

    ib = connect(client_id=client_id or cfg.CLIENT_ID, readonly=readonly)
    try:
        accounts = [str(account) for account in (ib.managedAccounts() or [])]
        account_summary = snapshot_account_summary(ib)
        positions = snapshot_positions(ib)
        open_orders = snapshot_open_orders(ib)
        executions = snapshot_executions(ib)
    finally:
        ib.disconnect()

    values = _account_values(account_summary)
    snapshot = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "client_id": client_id or cfg.CLIENT_ID,
        "readonly": bool(readonly),
        "accounts": accounts,
        "account_mode": _account_mode(accounts),
        "account_values": values,
        "account_summary": account_summary,
        "positions": positions,
        "open_orders": open_orders,
        "executions": executions,
    }
    validate_live_account_snapshot(snapshot)
    atomic_write_json(cfg.BROKER_SNAPSHOT_FILE, snapshot)
    return snapshot
