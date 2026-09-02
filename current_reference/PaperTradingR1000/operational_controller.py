"""Operational controller adapted from the Tradingbot2607 control model."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import config as cfg
from control_utils import clear_stop_request, request_stop, stop_bot_requested
from heartbeat_utils import write_heartbeat
from logger_utils import log
from monitoring_core import write_bot_status
from monitoring_io import atomic_write_json, utc_timestamp
from runtime_processes import clear_pid, is_pid_running, process_info, read_pid, write_pid
from runtime_health import HEALTH_OK, HEALTH_STOPPED, write_runtime_health
from strategy_scheduler import is_cycle_due, record_cycle_result, runtime_summary
from telegram_alerts import (
    alert_engine_failure,
    alert_market_data_refresh_failure,
    alert_market_data_refresh_warning,
    alert_scan_completed,
    alert_universe_refresh_failure,
)


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


UNIVERSE_WEEKLY_STATE_FILE = cfg.STATE_DIR / "iwb_universe_weekly_state.json"
UNIVERSE_REFRESH_STATUS_FILE = cfg.STATE_DIR / "iwb_universe_refresh.json"
UNIVERSE_REFRESH_TIME_ET = clock_time(7, 45)
MARKET_DATA_DAILY_STATE_FILE = cfg.STATE_DIR / "ibkr_market_data_daily_state.json"
MARKET_DATA_REFRESH_STATUS_FILE = cfg.STATE_DIR / "ibkr_market_data_refresh.json"
MARKET_DATA_REFRESH_TIME_ET = clock_time(8, 30)
NY_TZ = ZoneInfo("America/New_York")


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _universe_refresh_due(now: datetime | None = None) -> bool:
    now_et = (now or datetime.now(timezone.utc)).astimezone(NY_TZ)
    if now_et.time() < UNIVERSE_REFRESH_TIME_ET:
        return False
    state = _read_json_file(UNIVERSE_WEEKLY_STATE_FILE)
    today = now_et.date()
    if state.get("last_attempt_date_et") == today.isoformat():
        return False
    last_success_text = str(state.get("last_success_date_et") or "")
    if not last_success_text:
        return True
    try:
        last_success = datetime.fromisoformat(last_success_text).date()
    except ValueError:
        return True
    return today - last_success >= timedelta(days=7)


def run_weekly_universe_refresh(now: datetime | None = None) -> bool:
    now_et = (now or datetime.now(timezone.utc)).astimezone(NY_TZ)
    script = cfg.BASE_DIR / "iwb_universe_refresh.py"
    completed = subprocess.run([sys.executable, str(script)], cwd=str(cfg.BASE_DIR), text=True)
    status = _read_json_file(UNIVERSE_REFRESH_STATUS_FILE)
    ok = completed.returncode == 0 and str(status.get("status") or "").upper() == "OK"
    previous = _read_json_file(UNIVERSE_WEEKLY_STATE_FILE)
    state = {
        "last_attempt_date_et": now_et.date().isoformat(),
        "last_attempt_status": "OK" if ok else "FAILED",
        "completed_at_utc": utc_timestamp(),
        "last_success_date_et": now_et.date().isoformat() if ok else previous.get("last_success_date_et", ""),
        "as_of": status.get("as_of", ""),
        "unique_equity_symbols": status.get("unique_equity_symbols", ""),
    }
    atomic_write_json(UNIVERSE_WEEKLY_STATE_FILE, state)
    if not ok:
        alert_universe_refresh_failure(
            f"exit_code={completed.returncode}; error={status.get('error', 'unknown')}. "
            "Last validated IWB universe remains active and the refresh will retry on the next day."
        )
    return ok


def _market_data_refresh_due(now: datetime | None = None) -> bool:
    now_et = (now or datetime.now(timezone.utc)).astimezone(NY_TZ)
    if now_et.time() < MARKET_DATA_REFRESH_TIME_ET:
        return False
    state = _read_json_file(MARKET_DATA_DAILY_STATE_FILE)
    if state.get("attempt_date_et") == now_et.date().isoformat():
        return False
    previous_status = str(state.get("status") or "").upper()
    if not previous_status:
        previous_status = str(
            _read_json_file(MARKET_DATA_REFRESH_STATUS_FILE).get("status") or ""
        ).upper()
    # Normal refresh is every US-market weekday. Through the weekend, retry
    # only when the latest validated refresh itself is not OK. A stale/failed
    # daily-state marker must not override a newer validated OK refresh (for
    # example after a successful manual recovery on Saturday).
    validated_status = str(
        _read_json_file(MARKET_DATA_REFRESH_STATUS_FILE).get("status") or ""
    ).upper()
    if now_et.weekday() >= 5 and validated_status == "OK":
        return False
    return now_et.weekday() < 5 or previous_status != "OK"


def _run_market_data_refresh_once() -> int:
    script = cfg.BASE_DIR / "ibkr_daily_bar_refresh.py"
    command = [sys.executable, str(script), "--pause", "0.25"]
    log("controller refreshing IBKR daily bars", extra={"command": command})
    completed = subprocess.run(
        command,
        cwd=str(cfg.BASE_DIR),
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        log(
            "IBKR daily-bar refresher process failed",
            level="ERROR",
            extra={
                "exit_code": completed.returncode,
                "stdout_tail": (completed.stdout or "")[-2000:],
                "stderr_tail": (completed.stderr or "")[-4000:],
            },
        )
    return completed.returncode


def run_daily_market_data_refresh(now: datetime | None = None, attempts: int = 3) -> bool:
    now_et = (now or datetime.now(timezone.utc)).astimezone(NY_TZ)
    last_code = 1
    for attempt in range(1, max(1, attempts) + 1):
        last_code = _run_market_data_refresh_once()
        status = _read_json_file(MARKET_DATA_REFRESH_STATUS_FILE)
        refresh_state = str(status.get("status") or "").upper()
        if last_code == 0 and refresh_state in {"OK", "DEGRADED_ACCEPTABLE"}:
            daily_state = {
                "attempt_date_et": now_et.date().isoformat(),
                "status": refresh_state,
                "completed_at_utc": utc_timestamp(),
                "expected_latest_completed_session": status.get("expected_latest_completed_session"),
                "attempts": attempt,
                "failure_count": status.get("failure_count", 0),
                "acceptable_unresolved_symbols": status.get("acceptable_unresolved_symbols", []),
            }
            atomic_write_json(MARKET_DATA_DAILY_STATE_FILE, daily_state)
            if refresh_state == "DEGRADED_ACCEPTABLE":
                symbols = ",".join(status.get("acceptable_unresolved_symbols") or []) or "unknown"
                alert_market_data_refresh_warning(
                    f"Unresolved symbols: {symbols}; count={status.get('failure_count', 0)}; "
                    f"expected session={status.get('expected_latest_completed_session', 'unknown')}. "
                    "The refresher will retry automatically tomorrow."
                )
            return True
        if attempt < attempts:
            time.sleep(10)

    status = _read_json_file(MARKET_DATA_REFRESH_STATUS_FILE)
    detail = (
        f"attempts={attempts}; exit_code={last_code}; "
        f"failure_count={status.get('failure_count', 'unknown')}; "
        f"expected_session={status.get('expected_latest_completed_session', 'unknown')}"
    )
    atomic_write_json(
        MARKET_DATA_DAILY_STATE_FILE,
        {
            "attempt_date_et": now_et.date().isoformat(),
            "status": "FAILED",
            "completed_at_utc": utc_timestamp(),
            "detail": detail,
        },
    )
    alert_market_data_refresh_failure(detail)
    return False


def supervise(max_restarts: int = 3, net_liquidation_value: float | None = None) -> int:
    if not is_authorized():
        write_controller_status("BLOCKED", reason="boot_not_authorized")
        write_runtime_bot_status("STOPPED", "boot_not_authorized")
        return 2
    write_desired_running(True)
    restarts = 0
    while not stop_bot_requested():
        schedule = runtime_summary()
        if _universe_refresh_due():
            universe_ok = run_weekly_universe_refresh()
            if not universe_ok:
                log("weekly IWB universe refresh failed; continuing with last validated universe", level="WARNING")
        if _market_data_refresh_due():
            refresh_ok = run_daily_market_data_refresh()
            if not refresh_ok:
                log("daily IBKR market-data refresh failed; trading remains fail-closed", level="ERROR")
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
            alert_engine_failure(
                f"Strategy cycle raised {type(exc).__name__}: {exc}",
                extra={"restart_attempt": restarts},
            )
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
            selected_count = len(scan_report.get("selected_candidates", []))
            planned_count = (
                len(scan_report.get("order_plans", []))
                + len(scan_report.get("sell_order_plans", []))
            )

            automated_execution = scan_report.get("automated_execution", {}) or {}
            broker_submitted_count = int(
                automated_execution.get("broker_orders_transmitted", 0) or 0
            )

            explicit_rejected = len(
                automated_execution.get("rejected_orders", []) or []
            )
            duplicate_preventions = len(
                automated_execution.get("duplicate_preventions", []) or []
            )
            rejected_or_skipped_count = max(
                planned_count - broker_submitted_count,
                explicit_rejected + duplicate_preventions,
            )

            capital_control = scan_report.get("investable_capital_control", {}) or {}
            effective_investable_capital = float(
                    capital_control.get(
                        "operational_buy_budget",
                        capital_control.get("effective_investable_capital", 0.0),
                    )
                    or 0.0
                )

            alert_scan_completed(
                selected_count,
                planned_count,
                rejected_or_skipped_count,
                broker_submitted_count,
                effective_investable_capital,
            )
            restarts = 0
            continue
        restarts += 1
        write_controller_status("RESTART_PENDING", restart_attempt=restarts, last_exit_code=code)
        write_runtime_bot_status("RUNNING", "restart_pending", restart_attempt=restarts, last_exit_code=code)
        if restarts > max_restarts:
            write_controller_status("RETRY_COOLDOWN", last_exit_code=code)
            write_runtime_bot_status("RUNNING", "engine_failure_retry_cooldown", last_exit_code=code)
            alert_engine_failure(
                f"Strategy engine failed after {restarts} attempts; exit code {code}. Automatic retry will continue after cooldown.",
                extra={"restart_attempts": restarts, "last_exit_code": code},
            )
            # Do not exit: systemd would immediately restart the controller and
            # recreate an alert storm. Keep the controller alive and retry at a
            # deliberately slow cadence so transient IBKR/API outages can recover.
            restarts = 0
            deadline = time.monotonic() + 300
            while not stop_bot_requested() and time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))
            continue
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
