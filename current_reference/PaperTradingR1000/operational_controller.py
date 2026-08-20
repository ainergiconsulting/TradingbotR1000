"""Operational controller adapted from the Tradingbot2607 control model."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import config as cfg
from control_utils import clear_stop_request, request_stop, stop_bot_requested
from heartbeat_utils import write_heartbeat
from logger_utils import log
from monitoring_core import write_bot_status
from monitoring_io import atomic_write_json, utc_timestamp
from runtime_processes import clear_pid, is_pid_running, process_info, read_pid, write_pid
from runtime_health import HEALTH_OK, HEALTH_STOPPED, write_runtime_health
from strategy_scheduler import is_cycle_due, record_cycle_result, runtime_summary


def write_desired_running(running: bool) -> dict[str, Any]:
    payload = {"bot": cfg.BOT_NAME, "desired_running": running, "timestamp_utc": utc_timestamp()}
    atomic_write_json(cfg.DESIRED_STATE_FILE, payload)
    return payload


def authorize_current_boot() -> dict[str, Any]:
    payload = {"bot": cfg.BOT_NAME, "authorized": True, "timestamp_utc": utc_timestamp()}
    atomic_write_json(cfg.BOOT_AUTHORIZATION_FILE, payload)
    return payload


def is_authorized() -> bool:
    if not cfg.BOOT_AUTHORIZATION_FILE.exists():
        return False
    try:
        data = json.loads(cfg.BOOT_AUTHORIZATION_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return data.get("authorized") is True


def write_controller_status(status: str, **extra: Any) -> dict[str, Any]:
    payload = {"bot": cfg.BOT_NAME, "status": status, "timestamp_utc": utc_timestamp(), "pid": os.getpid()}
    payload.update(extra)
    atomic_write_json(cfg.CONTROLLER_STATUS_FILE, payload)
    return payload


def write_runtime_bot_status(status: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    payload = {
        "pid": os.getpid(),
        "runtime_process": status,
        "main_process": "operational_controller.py",
    }
    payload.update(extra)
    return write_bot_status(status, detail=detail, extra=payload)


def controller_process_status() -> dict[str, Any]:
    return process_info(cfg.CONTROLLER_PID_FILE)


def controller_is_running() -> bool:
    status = controller_process_status()
    return bool(status["running"])


def another_controller_running() -> bool:
    pid = read_pid(cfg.CONTROLLER_PID_FILE)
    return bool(pid and pid != os.getpid() and is_pid_running(pid))


def _last_reconciliation_status() -> str:
    try:
        data = json.loads(cfg.RECONCILIATION_REPORT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return "not_checked"
    return str(data.get("status") or "not_checked")


def write_idle_runtime_health(schedule: dict[str, Any]) -> None:
    write_runtime_health(
        strategy_engine_state="IDLE",
        order_engine_state=HEALTH_OK if cfg.EXECUTE_ORDERS else "DISABLED",
        startup_reconciliation_state=_last_reconciliation_status(),
        trading_state="TRADING_ENABLED" if cfg.EXECUTE_ORDERS else "TRADING_DISABLED",
        message="waiting_for_next_strategy_cycle",
        last_strategy_cycle_status=str(schedule.get("last_strategy_cycle_result") or ""),
        last_strategy_cycle_time_utc=str(schedule.get("last_strategy_cycle_utc") or ""),
        extra={"next_strategy_cycle": schedule.get("next_strategy_cycle_utc")},
    )


def run_engine_once(net_liquidation_value: float | None = None) -> int:
    engine = cfg.BASE_DIR / "trading_engine.py"
    command = [sys.executable, str(engine), "--scan-once"]
    if net_liquidation_value is not None:
        command.extend(["--net-liquidation-value", str(net_liquidation_value)])
    log("controller launching engine", extra={"command": command})
    completed = subprocess.run(command, cwd=str(cfg.PROJECT_ROOT), text=True)
    return completed.returncode


def supervise(max_restarts: int = 3, net_liquidation_value: float | None = None) -> int:
    if not is_authorized():
        write_controller_status("BLOCKED", reason="boot_not_authorized")
        write_runtime_bot_status("STOPPED", "boot_not_authorized")
        return 2
    write_desired_running(True)
    restarts = 0
    while not stop_bot_requested():
        schedule = runtime_summary()
        if not is_cycle_due():
            write_controller_status("IDLE", restart_attempt=restarts, next_strategy_cycle=schedule["next_strategy_cycle_utc"])
            write_idle_runtime_health(schedule)
            write_runtime_bot_status(
                "RUNNING",
                "waiting_for_next_strategy_cycle",
                restart_attempt=restarts,
                next_strategy_cycle=schedule["next_strategy_cycle_utc"],
            )
            write_heartbeat(event="controller_idle", next_strategy_cycle=schedule["next_strategy_cycle_utc"])
            deadline = time.monotonic() + max(1, cfg.CHECK_INTERVAL_SECONDS)
            while not stop_bot_requested() and time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))
            continue

        write_controller_status("RUNNING", restart_attempt=restarts, next_strategy_cycle=schedule["next_strategy_cycle_utc"])
        write_runtime_bot_status("RUNNING", "strategy_cycle_running", restart_attempt=restarts)
        try:
            code = run_engine_once(net_liquidation_value=net_liquidation_value)
        except Exception as exc:
            write_controller_status("FAILED", error=repr(exc), restart_attempt=restarts)
            write_runtime_bot_status("RUNNING", "strategy_cycle_failed", error=repr(exc), restart_attempt=restarts)
            raise
        if code == 0:
            try:
                scan_report = json.loads(cfg.SCAN_REPORT_FILE.read_text(encoding="utf-8"))
            except Exception:
                scan_report = {}
            record_cycle_result(
                cycle_id=str(scan_report.get("cycle_id") or utc_timestamp()),
                result="COMPLETED",
                cycle_time_utc=str(scan_report.get("timestamp_utc") or utc_timestamp()),
            )
            write_controller_status("IDLE", last_exit_code=code)
            write_runtime_bot_status("RUNNING", "controller_idle", last_exit_code=code)
            restarts = 0
            continue
        restarts += 1
        write_controller_status("RESTART_PENDING", restart_attempt=restarts, last_exit_code=code)
        write_runtime_bot_status("RUNNING", "restart_pending", restart_attempt=restarts, last_exit_code=code)
        if restarts > max_restarts:
            write_controller_status("MANUAL_INTERVENTION_REQUIRED", last_exit_code=code)
            write_runtime_bot_status("STOPPED", "manual_intervention_required", last_exit_code=code)
            return code
        time.sleep(5)
    write_desired_running(False)
    write_controller_status("STOPPED", reason="stop_requested")
    write_runtime_bot_status("STOPPED", "stop_requested")
    write_runtime_health(
        strategy_engine_state=HEALTH_STOPPED,
        order_engine_state=HEALTH_STOPPED,
        startup_reconciliation_state=_last_reconciliation_status(),
        trading_state="TRADING_DISABLED",
        message="stop_requested",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TradingbotR1000 operational controller")
    parser.add_argument("--authorize", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--net-liquidation-value", "--capital", dest="net_liquidation_value", type=float)
    args = parser.parse_args(argv)

    cfg.ensure_runtime_dirs()
    if args.authorize:
        clear_stop_request()
        authorize_current_boot()
        write_desired_running(True)
        print("authorized")
        return 0
    if args.stop:
        request_stop("operator_stop")
        target = controller_process_status()
        write_desired_running(False)
        write_controller_status("STOP_REQUESTED", pid=target.get("pid"), running=target.get("running"))
        print("stop requested")
        return 0
    if args.run_once:
        return run_engine_once(net_liquidation_value=args.net_liquidation_value)
    if another_controller_running():
        write_controller_status("ALREADY_RUNNING", existing_pid=read_pid(cfg.CONTROLLER_PID_FILE))
        print("controller already running")
        return 10
    write_pid(cfg.CONTROLLER_PID_FILE)
    write_runtime_bot_status("RUNNING", "controller_started")
    try:
        return supervise(net_liquidation_value=args.net_liquidation_value)
    finally:
        if not stop_bot_requested():
            write_desired_running(False)
            write_controller_status("STOPPED", reason="controller_process_exited")
            write_runtime_bot_status("STOPPED", "controller_process_exited")
        clear_pid(cfg.CONTROLLER_PID_FILE, os.getpid())


if __name__ == "__main__":
    raise SystemExit(main())
