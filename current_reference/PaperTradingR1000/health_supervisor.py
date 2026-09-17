"""Independent health supervisor for TradingbotR1000."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone

import config as cfg
from alert_utils import write_alert
from control_utils import stop_bot_requested
from gateway_status import collect_system_health
from heartbeat_utils import heartbeat_is_fresh
from monitoring_io import atomic_write_json, utc_timestamp
from runtime_processes import clear_pid, process_info, write_pid
from strategy_scheduler import NY_TZ, cycle_time, is_market_session_day, load_scheduler_state


IBKR_DEGRADED_AFTER_CONSECUTIVE_FAILURES = 3
IBKR_TRANSIENT_ERRORS = {
    "TIMEOUTERROR",
    "MONITORING_CLIENT_BUSY",
    "RUNTIMEERROR",
    "LIVE_PROBE_SKIPPED",
}

STRATEGY_CYCLE_MISSED_GRACE_MINUTES = 15

def strategy_cycle_watchdog(now: datetime | None = None) -> dict[str, object]:
    """Detect a daily strategy cycle that should already have completed.

    This is monitoring only: it never launches the strategy engine or orders.
    It prevents a silent missed trading day from being reported as healthy.
    """
    now_utc = now or datetime.now(timezone.utc)
    now_et = now_utc.astimezone(NY_TZ)
    today = now_et.date()
    if not is_market_session_day(today):
        return {"status": "NOT_DUE", "missed": False}
    target = cycle_time()
    due = now_et.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    deadline = due + timedelta(minutes=STRATEGY_CYCLE_MISSED_GRACE_MINUTES)
    if now_et < deadline:
        return {"status": "NOT_DUE", "missed": False, "deadline_et": deadline.isoformat()}
    state = load_scheduler_state()
    if state.get("last_cycle_date") == today.isoformat():
        return {"status": "COMPLETED", "missed": False, "last_cycle_date": state.get("last_cycle_date")}
    return {
        "status": "MISSED",
        "missed": True,
        "expected_cycle_date": today.isoformat(),
        "expected_cycle_time_et": target.strftime("%H:%M"),
        "last_cycle_date": state.get("last_cycle_date", ""),
    }


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

    if error in IBKR_TRANSIENT_ERRORS:
        return "TRANSIENT_FAILURE"

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
        raw_ibkr_status = _ibkr_connection_status(
            live_api_status,
            gateway_status=gateway_status,
            socket_status=socket_status,
            live_api_error=live_api_error,
        )
    except Exception as error:
        live_api_status = "UNKNOWN"
        raw_ibkr_status = "TRANSIENT_FAILURE"
        gateway_status = "UNKNOWN"
        socket_status = "UNKNOWN"
        live_api_error = type(error).__name__

    previous_ibkr_status = str(previous.get("ibkr_connection_status") or "").upper()
    previous_heartbeat_fresh = previous.get("heartbeat_fresh")
    previous_api_failures = int(previous.get("consecutive_api_failures") or 0)
    cycle_watch = strategy_cycle_watchdog()
    previous_cycle_watch = previous.get("strategy_cycle_watchdog") or {}

    if raw_ibkr_status == "CONNECTED":
        consecutive_api_failures = 0
        ibkr_status = "CONNECTED"
    elif raw_ibkr_status == "DISCONNECTED":
        consecutive_api_failures = previous_api_failures + 1
        ibkr_status = "DISCONNECTED"
    elif raw_ibkr_status == "TRANSIENT_FAILURE":
        consecutive_api_failures = previous_api_failures + 1
        ibkr_status = (
            "DEGRADED"
            if consecutive_api_failures >= IBKR_DEGRADED_AFTER_CONSECUTIVE_FAILURES
            else "UNKNOWN"
        )
    else:
        consecutive_api_failures = previous_api_failures + 1
        ibkr_status = "UNKNOWN"

    if previous_heartbeat_fresh is True and fresh is False:
        write_alert(
            "heartbeat_stale",
            "TradingbotR1000 heartbeat became stale.",
        )
    elif previous_heartbeat_fresh is False and fresh is True:
        write_alert(
            "heartbeat_recovered",
            "TradingbotR1000 heartbeat recovered.",
        )

    if ibkr_status == "DISCONNECTED" and previous_ibkr_status not in {"", "DISCONNECTED"}:
        write_alert(
            "ibkr_disconnected",
            (
                "IBKR live API connection lost. "
                f"Gateway={gateway_status}, socket={socket_status}, "
                f"error={live_api_error or 'none'}."
            ),
        )
    elif ibkr_status == "DEGRADED" and previous_ibkr_status != "DEGRADED":
        write_alert(
            "ibkr_degraded",
            (
                "IBKR live API is persistently unresponsive. "
                f"Consecutive failures={consecutive_api_failures}; "
                f"Gateway={gateway_status}, socket={socket_status}, "
                f"error={live_api_error or 'none'}. Trading remains fail-closed."
            ),
        )
    elif ibkr_status == "CONNECTED" and previous_ibkr_status in {"DISCONNECTED", "DEGRADED"}:
        write_alert(
            "ibkr_reconnected",
            "IBKR live API connection restored.",
        )

    if cycle_watch.get("missed") and not (isinstance(previous_cycle_watch, dict) and previous_cycle_watch.get("missed")):
        write_alert(
            "strategy_cycle_missed",
            (
                "TradingbotR1000 daily strategy cycle is missing after its grace period. "
                f"Expected {cycle_watch.get('expected_cycle_date')} "
                f"{cycle_watch.get('expected_cycle_time_et')} ET; "
                f"last completed={cycle_watch.get('last_cycle_date') or 'none'}."
            ),
        )

    if not fresh:
        overall_status = "STALE_HEARTBEAT"
    elif ibkr_status == "DEGRADED":
        overall_status = "DEGRADED_IBKR"
    elif ibkr_status == "DISCONNECTED":
        overall_status = "IBKR_DISCONNECTED"
    elif ibkr_status != "CONNECTED":
        overall_status = "IBKR_UNKNOWN"
    elif cycle_watch.get("missed"):
        overall_status = "STRATEGY_CYCLE_MISSED"
    else:
        overall_status = "OK"

    payload = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "heartbeat_fresh": fresh,
        "status": overall_status,
        "ibkr_connection_status": ibkr_status,
        "live_api_status": live_api_status,
        "gateway_process_status": gateway_status,
        "api_socket_status": socket_status,
        "live_api_error": live_api_error,
        "consecutive_api_failures": consecutive_api_failures,
        "strategy_cycle_watchdog": cycle_watch,
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
