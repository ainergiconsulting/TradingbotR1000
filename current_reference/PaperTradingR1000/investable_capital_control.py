"""Persistent investable-capital control for TradingbotR1000.

This is an operational capital control, not a strategy-rule module.  AUTO keeps
the approved 70% of live NLV calculation; MANUAL lets the operator choose the
fixed investable-capital amount the strategy sizing step receives.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from typing import Any

import config as cfg
from monitoring_io import atomic_write_json, utc_timestamp
from strategy import APPROVED_PARAMETERS


MODE_AUTO = "AUTO"
MODE_MANUAL = "MANUAL"
COMPLIANCE_OK = "OK"
COMPLIANCE_INVALID_IC_EXCEEDS_NLV = "INVALID - IC EXCEEDS NLV"


class InvestableCapitalControlError(ValueError):
    """Raised when the requested investable-capital setting is invalid."""


def _money(value: Any) -> float:
    text = str(value).replace(",", "").replace("$", "").upper().replace("USD", "").strip()
    try:
        decimal = Decimal(text)
    except (InvalidOperation, AttributeError) as exc:
        raise InvestableCapitalControlError("amount_must_be_numeric") from exc
    if not decimal.is_finite():
        raise InvestableCapitalControlError("amount_must_be_finite")
    if decimal < Decimal("0"):
        raise InvestableCapitalControlError("amount_must_not_be_negative")
    return float(decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def default_settings() -> dict[str, Any]:
    return {
        "bot": cfg.BOT_NAME,
        "mode": MODE_AUTO,
        "manual_amount_usd": None,
        "updated_at_utc": utc_timestamp(),
    }


def load_settings(path=None) -> dict[str, Any]:
    path = path or cfg.INVESTABLE_CAPITAL_CONTROL_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_settings()
    except json.JSONDecodeError:
        return default_settings()
    if not isinstance(data, dict):
        return default_settings()
    mode = str(data.get("mode") or MODE_AUTO).upper()
    if mode not in {MODE_AUTO, MODE_MANUAL}:
        mode = MODE_AUTO
    amount = data.get("manual_amount_usd")
    if mode == MODE_MANUAL:
        try:
            amount = _money(amount)
        except InvestableCapitalControlError:
            mode = MODE_AUTO
            amount = None
    else:
        amount = None
    return {
        "bot": cfg.BOT_NAME,
        "mode": mode,
        "manual_amount_usd": amount,
        "updated_at_utc": str(data.get("updated_at_utc") or ""),
    }


def save_settings(settings: dict[str, Any], path=None) -> dict[str, Any]:
    path = path or cfg.INVESTABLE_CAPITAL_CONTROL_FILE
    payload = dict(settings)
    payload["bot"] = cfg.BOT_NAME
    payload["mode"] = str(payload.get("mode") or MODE_AUTO).upper()
    payload["updated_at_utc"] = utc_timestamp()
    atomic_write_json(path, payload)
    return payload


def set_auto(path=None) -> dict[str, Any]:
    return save_settings(
        {
            "mode": MODE_AUTO,
            "manual_amount_usd": None,
        },
        path=path,
    )


def set_manual(amount: Any, *, live_net_liquidation: float | None = None, path=None) -> dict[str, Any]:
    value = _money(amount)
    if value <= 0:
        raise InvestableCapitalControlError("amount_must_be_positive")
    if live_net_liquidation is not None and value > float(live_net_liquidation):
        raise InvestableCapitalControlError("amount_exceeds_current_nlv")
    return save_settings(
        {
            "mode": MODE_MANUAL,
            "manual_amount_usd": value,
        },
        path=path,
    )


def evaluate(live_net_liquidation: Any, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    live_nlv = _money(live_net_liquidation)
    settings = settings or load_settings()
    mode = str(settings.get("mode") or MODE_AUTO).upper()
    if mode == MODE_MANUAL:
        configured = _money(settings.get("manual_amount_usd"))
        effective = configured
        compliance = COMPLIANCE_OK
        reason = ""
        if configured > live_nlv:
            compliance = COMPLIANCE_INVALID_IC_EXCEEDS_NLV
            reason = "manual_investable_capital_exceeds_live_nlv"
        reserve = live_nlv - effective
    else:
        mode = MODE_AUTO
        configured = round(live_nlv * APPROVED_PARAMETERS.investable_capital_pct, 2)
        effective = configured
        compliance = COMPLIANCE_OK
        reason = ""
        reserve = round(live_nlv * APPROVED_PARAMETERS.liquidity_reserve_pct, 2)

    return {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "mode": mode,
        "live_net_liquidation": live_nlv,
        "configured_investable_capital": configured,
        "effective_investable_capital": effective,
        "liquidity_reserve": round(reserve, 2),
        "compliance": compliance,
        "reason": reason,
        "manual_amount_usd": settings.get("manual_amount_usd"),
        "settings_file": str(cfg.INVESTABLE_CAPITAL_CONTROL_FILE),
    }


def format_usd(value: Any) -> str:
    try:
        return f"{float(value):,.2f} USD"
    except (TypeError, ValueError):
        return "N/A"
