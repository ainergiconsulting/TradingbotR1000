"""Fail-closed automated PAPER execution activation preflight."""

from __future__ import annotations

import json
from typing import Any

import config as cfg
from automated_order_store import find_duplicate, load_store, save_store
from config_loader import ensure_runtime_ready, load_universe_config
from live_account import collect_live_account_context
from monitoring_io import atomic_write_json, utc_timestamp
from quality_monitor import activate_monitoring
from reconciliation import reconcile_local_state
from trading_engine import load_daily_bar_data, load_universe_symbol_records, _resolve_project_path


ACTIVATION_PREFLIGHT_FILE = cfg.STATE_DIR / "automated_activation_preflight.json"
CRITICAL_DATA_REASONS = {
    "missing_market_data",
    "invalid_market_data_schema",
    "invalid_market_data_rows",
    "stale_market_data",
}


def _market_data_readiness() -> dict[str, Any]:
    universe_config = load_universe_config()
    universe_path = _resolve_project_path(universe_config["source_path"])
    daily_bars_dir = _resolve_project_path(universe_config["daily_bars_dir"])
    universe = load_universe_symbol_records(universe_path, universe_config.get("symbol_column", "symbol"))
    market_data = load_daily_bar_data(universe["symbols"], daily_bars_dir)
    exclusions = [
        row for row in market_data["status_rows"]
        if row.get("status") == "excluded"
        and (
            row.get("reason") in CRITICAL_DATA_REASONS
            or str(row.get("reason") or "").startswith("market_data_read_error:")
        )
    ]
    return {
        "universe_expected_symbols": len(universe["symbols"]),
        "universe_exclusions": universe["exclusions"],
        "symbols_successfully_loaded": len(market_data["closes_by_symbol"]),
        "latest_date": market_data["latest_date"],
        "timestamp_utc": market_data["timestamp_utc"],
        "critical_exclusions": exclusions,
        "critical_exclusion_count": len(exclusions),
    }


def _validate_order_persistence() -> dict[str, Any]:
    store = load_store()
    save_store(store)
    probe_intent = {
        "symbol": "__PREFLIGHT__",
        "side": "BUY",
        "order_type": "LIMIT",
        "limit_price": 1.0,
        "signal_date": "preflight",
        "strategy_version": "preflight",
        "configuration_sha256": "preflight",
    }
    duplicate_reason = find_duplicate(probe_intent, positions=[], open_orders=[])
    return {
        "orders_count": len(store.get("orders") or []),
        "write_ok": True,
        "duplicate_prevention_ok": duplicate_reason == "",
    }


def validate_automated_activation() -> dict[str, Any]:
    cfg.ensure_runtime_dirs()
    issues: list[str] = []
    evidence: dict[str, Any] = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "execution_switch": cfg.AUTOMATED_PAPER_EXECUTION_SWITCH,
        "execute_orders": cfg.EXECUTE_ORDERS,
    }

    if not cfg.EXECUTE_ORDERS:
        issues.append("automated_execution_switch_not_enabled")

    try:
        evidence["configuration"] = ensure_runtime_ready(require_universe_file=True)
    except Exception as error:
        issues.append(f"configuration_invalid:{type(error).__name__}:{error}")

    try:
        evidence["order_persistence"] = _validate_order_persistence()
        if not evidence["order_persistence"]["duplicate_prevention_ok"]:
            issues.append("duplicate_prevention_preflight_failed")
    except Exception as error:
        issues.append(f"order_persistence_unavailable:{type(error).__name__}:{error}")

    try:
        broker_context = collect_live_account_context(client_id=cfg.RECONCILIATION_CLIENT_ID, readonly=True)
        evidence["account"] = {
            "timestamp_utc": broker_context["timestamp_utc"],
            "client_id": broker_context.get("client_id"),
            "account_mode": broker_context.get("account_mode"),
            "accounts": broker_context.get("accounts", []),
            "account_values": broker_context.get("account_values", {}),
            "positions_count": len(broker_context.get("positions") or []),
            "open_orders_count": len(broker_context.get("open_orders") or []),
        }
    except Exception as error:
        broker_context = {}
        issues.append(f"live_account_unavailable:{type(error).__name__}:{error}")

    try:
        from gateway_status import collect_system_health

        health = collect_system_health()
        evidence["system_health"] = {
            "gateway_process_status": health.get("gateway_process_status"),
            "api_socket_status": health.get("api_socket_status"),
            "live_api_status": health.get("live_api_status"),
            "market_status": health.get("market_status"),
            "liquid_hours_status": health.get("liquid_hours_status"),
            "trading_enabled": health.get("trading_enabled"),
            "reason_trading_disabled": health.get("reason_trading_disabled"),
        }
        if health.get("api_socket_status") != "CONNECTED" and health.get("live_api_status") not in {"CONNECTED", "CONNECTED_LAST_KNOWN"}:
            issues.append("ibkr_gateway_or_api_not_connected")
    except Exception as error:
        issues.append(f"system_health_unavailable:{type(error).__name__}:{error}")

    try:
        data = _market_data_readiness()
        evidence["market_data"] = data
        if not data["latest_date"]:
            issues.append("market_data_latest_date_unavailable")
        if data["critical_exclusion_count"]:
            symbols = ",".join(row["symbol"] for row in data["critical_exclusions"][:20])
            issues.append(f"market_data_not_current_or_invalid:{data['critical_exclusion_count']}:{symbols}")
    except Exception as error:
        issues.append(f"market_data_validation_failed:{type(error).__name__}:{error}")

    if broker_context:
        try:
            reconciliation = reconcile_local_state(broker_snapshot=broker_context)
            evidence["reconciliation"] = {
                "timestamp_utc": reconciliation.get("timestamp_utc"),
                "status": reconciliation.get("status"),
                "broker_position_count": reconciliation.get("broker_position_count"),
                "broker_open_order_count": reconciliation.get("broker_open_order_count"),
            }
            if reconciliation.get("status") != "RECONCILED":
                issues.append(f"reconciliation_not_current:{reconciliation.get('status')}")
        except Exception as error:
            issues.append(f"reconciliation_failed:{type(error).__name__}:{error}")

    evidence["ok"] = not issues
    evidence["issues"] = issues
    if evidence["ok"]:
        evidence["quality_monitoring"] = activate_monitoring()
    atomic_write_json(ACTIVATION_PREFLIGHT_FILE, evidence)
    return evidence


def main() -> int:
    result = validate_automated_activation()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
