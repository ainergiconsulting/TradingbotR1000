"""Read-only IBKR API socket preflight for local operator launchers.

This script does not connect through the IBKR API protocol and does not place
orders.  It only verifies whether the configured TCP endpoint accepts a socket
connection before tools such as the Manual Control Console are launched.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT_DIR / "current_reference" / "PaperTradingR1000"
STATE_DIR = BOT_DIR / "state"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _socket_reachable(host: str, port: int, timeout_seconds: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, "reachable"
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def _state_timestamp(payload: dict[str, Any]) -> Any:
    return payload.get("timestamp", payload.get("timestamp_utc", "unknown"))


def _bot_status_text(bot_status: dict[str, Any], health: dict[str, Any]) -> str:
    return str(
        health.get("bot_status")
        or bot_status.get("status")
        or ("BOT NOT RUNNING" if health.get("bot_not_running") else "unknown")
    )


def load_config():
    sys.path.insert(0, str(BOT_DIR))
    import config  # noqa: PLC0415

    return config


def build_report(timeout_seconds: float) -> tuple[int, list[str]]:
    if str(BOT_DIR) not in sys.path:
        sys.path.insert(0, str(BOT_DIR))
    cfg = load_config()
    from gateway_status import collect_system_health, format_status_lines  # noqa: PLC0415

    host = str(cfg.HOST)
    port = int(cfg.PORT)
    ok, status = _socket_reachable(host, port, timeout_seconds)
    health = collect_system_health()

    heartbeat = _read_json(STATE_DIR / "heartbeat.json")
    bot_status = _read_json(STATE_DIR / "bot_status.json")

    lines = [
        "IBKR API preflight",
        f"Configured endpoint: {host}:{port}",
        f"Trading bot client ID: {getattr(cfg, 'CLIENT_ID', 'unknown')}",
        f"Manual console client ID: {getattr(cfg, 'MANUAL_CLIENT_ID', 'unknown')}",
        f"Reconciliation client ID: {getattr(cfg, 'RECONCILIATION_CLIENT_ID', 'unknown')}",
        f"Socket reachable: {'yes' if ok else 'no'}",
        f"Socket status: {status}",
        f"System state: {health.get('system_state', 'UNKNOWN')}",
        f"Recovery reason: {health.get('recovery_reason', 'UNKNOWN')}",
        f"Severity: {health.get('severity', 'UNKNOWN')}",
        f"Trading enabled: {'YES' if health.get('trading_enabled') else 'NO'}",
        f"Trading disabled reason: {health.get('reason_trading_disabled') or 'None'}",
        f"Bot status file: {_bot_status_text(bot_status, health)} | connected={bot_status.get('connected', 'unknown')} | timestamp={_state_timestamp(bot_status)}",
        f"Heartbeat file: {heartbeat.get('status', 'unknown')} | connected={heartbeat.get('connected', heartbeat.get('ib_connected', 'unknown'))} | timestamp={_state_timestamp(heartbeat)}",
        "Historical snapshots: not used by operational preflight",
    ]

    if ok:
        lines.append("RESULT: OK - IBKR API TCP endpoint is accepting connections.")
        lines.extend(["", "Structured status:"])
        lines.extend(format_status_lines(health))
        return 0, lines

    lines.extend(
        [
            "RESULT: FAILED - IBKR API TCP endpoint is not accepting connections.",
            "This is a TCP/socket failure before IBKR API negotiation.",
            "Likely causes: IB Gateway/TWS not running, not logged in, API disabled, wrong paper/live port, API not fully ready, or listener bound to a different interface.",
            "Manual Control Console was not launched.",
        ]
    )
    return 70, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check configured IBKR API TCP endpoint.")
    parser.add_argument("--timeout-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    exit_code, lines = build_report(args.timeout_seconds)
    print("\n".join(lines))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
