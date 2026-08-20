"""Configuration loading and validation for TradingbotR1000."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import config as cfg
from strategy import APPROVED_PARAMETERS, STRATEGY_VERSION


class ConfigError(ValueError):
    """Raised when local implementation configuration is invalid."""


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing_config_file:{path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ConfigError(f"config_not_object:{path}")
    return data


def _read_optional_json_object(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return dict(default)
    except json.JSONDecodeError:
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def _sha256_payload(*payloads: dict[str, Any]) -> str:
    text = json.dumps(payloads, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_strategy_constants() -> dict[str, Any]:
    data = _read_json_object(cfg.STRATEGY_CONSTANTS_FILE)
    expected = asdict(APPROVED_PARAMETERS)
    expected["strategy_version"] = STRATEGY_VERSION
    for key, value in expected.items():
        if data.get(key) != value:
            raise ConfigError(f"strategy_constant_mismatch:{key}")
    return data


def load_universe_config() -> dict[str, Any]:
    data = _read_json_object(cfg.UNIVERSE_CONFIG_FILE)
    if data.get("universe") != APPROVED_PARAMETERS.universe:
        raise ConfigError("universe_must_be_russell_1000_stocks")
    source_type = data.get("source_type")
    if source_type not in {"csv"}:
        raise ConfigError("universe_source_type_must_be_csv")
    source_path = data.get("source_path")
    if not isinstance(source_path, str) or not source_path.strip():
        raise ConfigError("universe_source_path_required")
    daily_bars_dir = data.get("daily_bars_dir")
    if not isinstance(daily_bars_dir, str) or not daily_bars_dir.strip():
        raise ConfigError("daily_bars_dir_required")
    symbol_column = data.get("symbol_column")
    if not isinstance(symbol_column, str) or not symbol_column.strip():
        raise ConfigError("universe_symbol_column_required")
    return data


def load_order_execution_config() -> dict[str, Any]:
    data = _read_json_object(cfg.ORDER_EXECUTION_CONFIG_FILE)
    if data.get("allow_short") is not False:
        raise ConfigError("allow_short_must_be_false")
    if data.get("allow_long") is not True:
        raise ConfigError("allow_long_must_be_true")
    if data.get("paper_trading_required") is not True:
        raise ConfigError("paper_trading_required_must_be_true")
    forbidden_strategy_keys = {
        "order_type",
        "time_in_force",
        "cash_reserve_pct",
        "investable_capital_pct",
        "target_position_pct",
        "liquidity_filter",
        "sector_filter",
        "volatility_filter",
        "market_regime_filter",
    }
    present = forbidden_strategy_keys.intersection(data)
    if present:
        raise ConfigError("order_execution_config_contains_strategy_rule:" + ",".join(sorted(present)))
    return data


def validate_config_files(require_universe_file: bool = False) -> dict[str, Any]:
    strategy_constants = load_strategy_constants()
    universe = load_universe_config()
    order_execution = load_order_execution_config()
    runtime_execution = {
        "automated_execution_switch": cfg.AUTOMATED_PAPER_EXECUTION_SWITCH,
        "execute_orders": cfg.EXECUTE_ORDERS,
        "paper_trading_required": cfg.PAPER_TRADING_REQUIRED,
        "strategy_cycle_time_et": cfg.STRATEGY_CYCLE_TIME_ET,
        "strategy_cycle_timezone": cfg.STRATEGY_CYCLE_TIMEZONE,
    }
    investable_capital_control = _read_optional_json_object(
        cfg.INVESTABLE_CAPITAL_CONTROL_FILE,
        {"mode": "AUTO", "manual_amount_usd": None},
    )
    investable_capital_control = {
        "mode": str(investable_capital_control.get("mode") or "AUTO").upper(),
        "manual_amount_usd": investable_capital_control.get("manual_amount_usd"),
    }

    source_path = (cfg.PROJECT_ROOT / universe["source_path"]).resolve()
    daily_bars_dir = (cfg.PROJECT_ROOT / universe["daily_bars_dir"]).resolve()
    if require_universe_file and not source_path.exists():
        raise ConfigError(f"universe_source_missing:{source_path}")

    snapshot = {
        "strategy_constants": strategy_constants,
        "universe_config": universe,
        "order_execution_config": order_execution,
        "runtime_execution_config": runtime_execution,
        "investable_capital_control": investable_capital_control,
        "universe_source_exists": source_path.exists(),
        "universe_source_path": str(source_path),
        "daily_bars_dir_exists": daily_bars_dir.exists(),
        "daily_bars_dir": str(daily_bars_dir),
    }
    snapshot["effective_configuration_sha256"] = _sha256_payload(
        strategy_constants,
        universe,
        order_execution,
        runtime_execution,
        investable_capital_control,
    )
    return snapshot


def load_config_snapshot() -> dict[str, Any]:
    return validate_config_files(require_universe_file=False)


def ensure_runtime_ready(require_universe_file: bool = False) -> dict[str, Any]:
    cfg.ensure_runtime_dirs()
    return validate_config_files(require_universe_file=require_universe_file)
