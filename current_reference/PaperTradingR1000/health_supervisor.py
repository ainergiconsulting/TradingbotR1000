"""Independent health supervisor for TradingbotR1000."""

from __future__ import annotations

import argparse
import json
import os
import time

import config as cfg
from alert_utils import write_alert
from control_utils import stop_bot_requested
from gateway_status import collect_system_health
from heartbeat_utils import heartbeat_is_fresh
from monitoring_io import atomic_write_json, utc_timestamp
from runtime_processes import clear_pid, process_info, write_pid


def _previous_supervisor_status() -> dict[str, object]:
    try:
        data = json.loads(cfg.SUPERVISOR_STATUS_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _ibkr_connection_status(
    live_api_status: object,
    *,
    gateway_status: object = "",
    socket_status: object = "",
    live_api_error: object = "",
) -> str:
    value = str(live_api_status or "").strip().upper()
    gateway = str(gateway_status or "").strip().upper()
    socket = str(socket_status or "").strip().upper()
    error = str(live_api_error or "").strip().upper()

    if value in {"CONNECTED", "CONNECTED_LAST_KNOWN"}:
        return "CONNECTED"

    if gateway == "ABSENT" or socket in {"CONNECTION_REFUSED", "CLOSED"}:
        return "DISCONNECTED"

    if error in {
        "TIMEOUTERROR",
        "MONITORING_CLIENT_BUSY",
        "RUNTIMEERROR",
        "LIVE_PROBE_SKIPPED",
    }:
        return "UNKNOWN"

    if value == "DISCONNECTED":
        return "DISCONNECTED"

    return "UNKNOWN"


def evaluate_health(max_heartbeat_age_seconds: int = 180) -> dict[str, object]:
    fresh = heartbeat_is_fresh(max_age_seconds=max_heartbeat_age_seconds)
    previous = _previous_supervisor_status()

    try:
        system_health = collect_system_health()
        live_api_status = str(system_health.get("live_api_status") or "UNKNOWN").upper()
        gateway_status = str(system_health.get("gateway_process_status") or "UNKNOWN")
        socket_status = str(system_health.get("api_socket_status") or "UNKNOWN")
        live_api_error = str(system_health.get("live_api_error") or "")
        ibkr_status = _ibkr_connection_status(
            live_api_status,
            gateway_status=gateway_status,
            socket_status=socket_status,
            live_api_error=live_api_error,
        )
    except Exception as error:
        live_api_status = "UNKNOWN"
        ibkr_status = "UNKNOWN"
        gateway_status = "UNKNOWN"
        socket_status = "UNKNOWN"
        live_api_error = type(error).__name__

    previous_ibkr_status = str(previous.get("ibkr_connection_status") or "").upper()

    if previous_ibkr_status == "CONNECTED" and ibkr_status == "DISCONNECTED":
        write_alert(
            "ibkr_disconnected",
            (
                "IBKR live API connection lost. "
                f"Gateway={gateway_status}, socket={socket_status}, "
                f"error={live_api_error or 'none'}."
            ),
        )
    elif previous_ibkr_status == "DISCONNECTED" and ibkr_status == "CONNECTED":
        write_alert(
            "ibkr_reconnected",
            "IBKR live API connection restored.",
        )

    payload = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "heartbeat_fresh": fresh,
        "status": "OK" if fresh else "STALE_HEARTBEAT",
        "ibkr_connection_status": ibkr_status,
        "live_api_status": live_api_status,
        "gateway_process_status": gateway_status,
        "api_socket_status": socket_status,
        "live_api_error": live_api_error,
    }
    atomic_write_json(cfg.SUPERVISOR_STATUS_FILE, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TradingbotR1000 health supervisor")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args(argv)
    cfg.ensure_runtime_dirs()
    if args.once:
        payload = evaluate_health()
        print(json.dumps(payload, indent=2))
        return 0 if payload["heartbeat_fresh"] else 2

    status = process_info(cfg.SUPERVISOR_PID_FILE)
    if status["running"] and status["pid"] != os.getpid():
        atomic_write_json(
            cfg.SUPERVISOR_STATUS_FILE,
            {
                "bot": cfg.BOT_NAME,
                "timestamp_utc": utc_timestamp(),
                "status": "ALREADY_RUNNING",
                "existing_pid": status["pid"],
            },
        )
        print(json.dumps({"status": "ALREADY_RUNNING", "existing_pid": status["pid"]}, indent=2))
        return 10

    write_pid(cfg.SUPERVISOR_PID_FILE)
    try:
        while not stop_bot_requested():
            payload = evaluate_health()
            print(json.dumps(payload, indent=2))
            deadline = time.monotonic() + max(1, args.interval)
            while time.monotonic() < deadline:
                if stop_bot_requested():
                    break
                time.sleep(min(1.0, deadline - time.monotonic()))
        payload = {
            "bot": cfg.BOT_NAME,
            "timestamp_utc": utc_timestamp(),
            "heartbeat_fresh": heartbeat_is_fresh(),
            "status": "STOPPED",
            "reason": "stop_requested",
        }
        atomic_write_json(cfg.SUPERVISOR_STATUS_FILE, payload)
        print(json.dumps(payload, indent=2))
        return 0
    finally:
        if not stop_bot_requested():
            atomic_write_json(
                cfg.SUPERVISOR_STATUS_FILE,
                {
                    "bot": cfg.BOT_NAME,
                    "timestamp_utc": utc_timestamp(),
                    "heartbeat_fresh": heartbeat_is_fresh(),
                    "status": "STOPPED",
                    "reason": "supervisor_process_exited",
                },
            )
        clear_pid(cfg.SUPERVISOR_PID_FILE, os.getpid())


if __name__ == "__main__":
    raise SystemExit(main())
