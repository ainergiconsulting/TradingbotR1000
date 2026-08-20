"""Independent health supervisor for TradingbotR1000."""

from __future__ import annotations

import argparse
import json
import os
import time

import config as cfg
from control_utils import stop_bot_requested
from heartbeat_utils import heartbeat_is_fresh
from monitoring_io import atomic_write_json, utc_timestamp
from runtime_processes import clear_pid, process_info, write_pid


def evaluate_health(max_heartbeat_age_seconds: int = 180) -> dict[str, object]:
    fresh = heartbeat_is_fresh(max_age_seconds=max_heartbeat_age_seconds)
    payload = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "heartbeat_fresh": fresh,
        "status": "OK" if fresh else "STALE_HEARTBEAT",
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
