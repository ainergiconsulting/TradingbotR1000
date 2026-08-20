"""Startup preflight checks for TradingbotR1000."""

from __future__ import annotations

import importlib.util
import json
from typing import Any

import config as cfg
from config_loader import ConfigError, ensure_runtime_ready
from gateway_status import check_socket
from monitoring_io import atomic_write_json, utc_timestamp


def _dependency_status(name: str) -> dict[str, Any]:
    return {"name": name, "available": importlib.util.find_spec(name) is not None}


def validate_startup(require_universe_file: bool = False, require_gateway: bool = False) -> dict[str, Any]:
    issues: list[str] = []
    try:
        config_snapshot = ensure_runtime_ready(require_universe_file=require_universe_file)
    except ConfigError as exc:
        config_snapshot = {}
        issues.append(str(exc))

    dependencies = [_dependency_status("ib_insync"), _dependency_status("pandas"), _dependency_status("openpyxl")]
    socket_status = check_socket()
    if require_gateway and not socket_status["socket_reachable"]:
        issues.append("ibkr_gateway_not_reachable")
    if cfg.EXECUTE_ORDERS and not cfg.PAPER_TRADING_REQUIRED:
        issues.append("paper_trading_required_disabled")

    payload = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "status": "OK" if not issues else "FAILED",
        "ok": not issues,
        "issues": issues,
        "configuration": config_snapshot,
        "dependencies": dependencies,
        "ibkr_gateway": socket_status,
        "execute_orders": cfg.EXECUTE_ORDERS,
    }
    atomic_write_json(cfg.STATE_DIR / "startup_validation.json", payload)
    return payload


def main() -> int:
    result = validate_startup(require_universe_file=False, require_gateway=False)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
