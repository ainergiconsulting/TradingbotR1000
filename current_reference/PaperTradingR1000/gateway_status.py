"""Read-only Gateway/API readiness and operational visibility model.

This module is infrastructure-only.  It does not place orders, cancel orders,
modify strategy state, or attempt credential automation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
try:
    import msvcrt
except ImportError:
    msvcrt = None
    import fcntl
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Stock

import config as cfg
from ibkr_utils import (
    MARKET_HOURS_TIME_UNAVAILABLE_REASON,
    get_ibkr_server_time,
    ibkr_request_timeout,
    set_ibkr_request_timeout,
)
from monitoring_io import atomic_write_json
from operational_api_snapshot import snapshot_account_summary, snapshot_open_orders, snapshot_positions
from runtime_processes import process_info
from automated_order_store import runtime_summary as automated_order_runtime_summary
from investable_capital_control import evaluate as evaluate_investable_capital_control
from strategy_scheduler import runtime_summary as scheduler_runtime_summary


BASE_DIR = Path(cfg.BASE_DIR)
STATE_DIR = BASE_DIR / "state"
SYSTEM_HEALTH_FILE = STATE_DIR / "system_health.json"
API_PROBE_LOCK_FILE = STATE_DIR / "ibkr_monitor_client.lock"
STARTUP_VALIDATION_FILE = STATE_DIR / "startup_validation.json"
RUNTIME_HEALTH_FILE = STATE_DIR / "runtime_health.json"
RECONCILIATION_BASELINE_FILE = STATE_DIR / "recon_baseline.json"
CURRENT_RECONCILIATION_FILE = cfg.RECONCILIATION_REPORT_FILE

GATEWAY_PROCESS_NAMES = {"ibgateway.exe", "java.exe", "javaw.exe"}
ORDER_PENDING_REVIEW_MINUTES = 15
API_SNAPSHOT_MAX_AGE_SECONDS = 300
CACHED_LIVE_MAX_AGE_SECONDS = 180
MARKET_HOURS_CONTRACT_SYMBOL = "SPY"
MARKET_HOURS_SCHEDULE_UNAVAILABLE_REASON = (
    "Market-hours status unavailable: IBKR contractDetails unavailable"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None = None) -> str:
    dt = dt or utc_now()
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def runtime_execute_orders() -> tuple[bool, str]:
    runtime = read_json(RUNTIME_HEALTH_FILE, {})
    if isinstance(runtime, dict):
        runtime_state = str(runtime.get("trading_state", "") or "").upper()
        if runtime_state in {"TRADING_DISABLED", "TRADING_BLOCKED"}:
            return False, "runtime_health"
    activation = read_json(cfg.STATE_DIR / "automated_activation_preflight.json", {})
    if isinstance(activation, dict) and activation.get("execute_orders") is True and activation.get("ok") is False:
        return False, "activation_preflight"
    startup = read_json(STARTUP_VALIDATION_FILE, {})
    if (
        isinstance(startup, dict)
        and startup.get("status") == "OK"
        and isinstance(startup.get("execute_orders"), bool)
    ):
        return bool(startup["execute_orders"]), "startup_validation"
    return bool(getattr(cfg, "EXECUTE_ORDERS", False)), "process_config"


def runtime_health_state() -> dict[str, Any]:
    data = read_json(RUNTIME_HEALTH_FILE, {})
    return data if isinstance(data, dict) else {}


def runtime_safety_blocked(runtime_health: dict[str, Any]) -> bool:
    if not isinstance(runtime_health, dict) or not runtime_health:
        return False
    if str(runtime_health.get("trading_state", "") or "").upper() == "TRADING_BLOCKED":
        return True
    return any(
        str(runtime_health.get(field, "") or "").upper() == "FAILED"
        for field in (
            "strategy_engine_state",
            "order_engine_state",
            "startup_reconciliation_state",
        )
    )


def apply_runtime_health_override(
    state: str,
    recovery_reason: str,
    severity: str,
    runtime_health: dict[str, Any],
) -> tuple[str, str, str]:
    if runtime_safety_blocked(runtime_health):
        return "TRADING_BLOCKED", "RUNTIME_SAFETY_BLOCKED", "CRITICAL"
    return state, recovery_reason, severity


def parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _timestamp_value(payload: dict[str, Any]) -> str:
    return str(payload.get("timestamp_utc") or payload.get("timestamp") or "").strip()


def _format_age(seconds: float | None) -> str:
    if seconds is None:
        return "age unknown"
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m ago"
    if minutes:
        return f"{minutes}m {secs}s ago"
    return f"{secs}s ago"


def _timestamp_age_text(timestamp: str, now: datetime) -> str:
    parsed = parse_utc(timestamp)
    if parsed is None:
        return "age unknown"
    return _format_age((now - parsed).total_seconds())


def _last_cycle_status(runtime_health: dict[str, Any], scan_report: dict[str, Any]) -> str:
    explicit = str(runtime_health.get("last_strategy_cycle_status") or "").strip().upper()
    if explicit:
        return explicit
    engine_state = str(runtime_health.get("strategy_engine_state") or "").strip().upper()
    message = str(runtime_health.get("message") or "").strip().lower()
    if engine_state in {"STARTING", "RUNNING"}:
        return "RUNNING"
    if engine_state in {"FAILED", "ERROR"}:
        return "FAILED"
    if "scan completed" in message or _timestamp_value(scan_report):
        return "COMPLETED"
    return "not checked"


def _last_cycle_time(runtime_health: dict[str, Any], scan_report: dict[str, Any]) -> str:
    explicit = str(runtime_health.get("last_strategy_cycle_time_utc") or "").strip()
    if explicit:
        return explicit
    if "last_strategy_cycle_status" in runtime_health:
        return ""
    return str(scan_report.get("timestamp_utc") or scan_report.get("timestamp") or "").strip()


def _strategy_engine_display(
    *,
    runtime_running: bool,
    controller_status: dict[str, Any],
    runtime_health: dict[str, Any],
) -> str:
    if not runtime_running:
        return "STOPPED"
    controller_state = str(controller_status.get("status") or "").strip().upper()
    engine_state = str(runtime_health.get("strategy_engine_state") or "").strip().upper()
    if controller_state == "RUNNING" or engine_state in {"STARTING", "RUNNING"}:
        return "RUNNING"
    if controller_state in {"FAILED", "MANUAL_INTERVENTION_REQUIRED"} or engine_state in {"FAILED", "ERROR"}:
        return "ERROR"
    return "IDLE"


def runtime_execution_status(now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    controller_process = process_info(cfg.CONTROLLER_PID_FILE)
    supervisor_process = process_info(cfg.SUPERVISOR_PID_FILE)
    controller_status = read_json(cfg.CONTROLLER_STATUS_FILE, {})
    bot_status = read_json(cfg.BOT_STATUS_FILE, {})
    heartbeat = read_json(cfg.HEARTBEAT_FILE, {})
    runtime_health = runtime_health_state()
    scan_report = read_json(cfg.SCAN_REPORT_FILE, {})

    runtime_running = bool(controller_process.get("running"))
    scheduler_running = bool(supervisor_process.get("running"))
    heartbeat_time = _timestamp_value(heartbeat)
    cycle_time = _last_cycle_time(runtime_health, scan_report)
    stored_bot_status = str(bot_status.get("status") or "").strip().upper()
    displayed_bot_status = "RUNNING" if runtime_running else "STOPPED"
    if runtime_running and stored_bot_status and stored_bot_status != "RUNNING":
        displayed_bot_status = stored_bot_status

    return {
        "runtime_process": "RUNNING" if runtime_running else "STOPPED",
        "runtime_pid": controller_process.get("pid"),
        "scheduler": "RUNNING" if scheduler_running else "STOPPED",
        "scheduler_pid": supervisor_process.get("pid"),
        "bot_status": displayed_bot_status,
        "bot_status_file_status": stored_bot_status or "MISSING",
        "bot_not_running": not runtime_running,
        "strategy_engine": _strategy_engine_display(
            runtime_running=runtime_running,
            controller_status=controller_status,
            runtime_health=runtime_health,
        ),
        "last_heartbeat_timestamp": heartbeat_time or "missing",
        "last_heartbeat_age": _timestamp_age_text(heartbeat_time, now) if heartbeat_time else "missing",
        "last_strategy_cycle": _last_cycle_status(runtime_health, scan_report),
        "last_cycle_time": cycle_time or "not checked",
        "controller_status": controller_status,
        "bot_status_file": bot_status,
        "heartbeat": heartbeat,
        "runtime_health": runtime_health,
    }


def latest_json_file(path: Path) -> Path | None:
    try:
        files = sorted(path.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    except Exception:
        return None
    return files[0] if files else None


def latest_api_snapshot() -> tuple[Path | None, dict[str, Any]]:
    # Historical diagnostic snapshots are excluded from operational runtime.
    # Current status is derived from live evidence and cached system health.
    return None, {}


def cached_system_health(now: datetime | None = None, max_age_seconds: int = CACHED_LIVE_MAX_AGE_SECONDS) -> dict[str, Any]:
    now = now or utc_now()
    data = read_json(SYSTEM_HEALTH_FILE, {})
    if not isinstance(data, dict):
        return {}
    timestamp = parse_utc(data.get("timestamp"))
    if timestamp is None:
        return {}
    age = (now - timestamp).total_seconds()
    if age < 0 or age > max_age_seconds:
        return {}
    data["_cache_age_seconds"] = round(age, 1)
    return data


def _acquire_probe_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        handle = open(API_PROBE_LOCK_FILE, "a+b")
    except OSError:
        return None
    try:
        handle.seek(0)
        if msvcrt is not None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        handle.close()
        return None


def _release_probe_lock(handle) -> None:
    if handle is None:
        return
    try:
        handle.seek(0)
        if msvcrt is not None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    handle.close()


def collect_live_api_evidence(host: str, port: int) -> dict[str, Any]:
    """Collect current read-only IBKR API evidence for operational status.

    This does not save a diagnostic snapshot and does not submit, modify, or
    cancel orders. Use exactly one configured monitoring client ID so status
    checks do not create a long trail of IB Gateway API-message tabs.
    """
    client_id = int(getattr(cfg, "REMOTE_CONTROL_CLIENT_ID", 23))
    lock_handle = _acquire_probe_lock()
    if lock_handle is None:
        return {
            "connected": False,
            "timestamp": iso_utc(),
            "client_id": client_id,
            "account_summary": [],
            "positions": [],
            "open_orders": [],
            "error": "MONITORING_CLIENT_BUSY",
        }

    ib = IB()
    try:
        ib.connect(host, int(port), clientId=client_id, timeout=5)
        set_ibkr_request_timeout(ib)
        server_time = get_ibkr_server_time(ib)
        positions = snapshot_positions(ib)
        return {
            "connected": bool(ib.isConnected()),
            "timestamp": iso_utc(),
            "client_id": client_id,
            "server_time": iso_utc(server_time) if server_time else "",
            "server_time_source": "IBKR_SERVER_TIME" if server_time else "UNAVAILABLE",
            "account_summary": snapshot_account_summary(ib),
            "positions": positions,
            "open_orders": snapshot_open_orders(ib),
            "market_hours": collect_ibkr_market_hours(ib, positions, server_time),
            "error": "",
        }
    except Exception as error:
        last_error = type(error).__name__
    finally:
        try:
            if ib.isConnected():
                ib.disconnect()
        except Exception:
            pass
        _release_probe_lock(lock_handle)
    return {
        "connected": False,
        "timestamp": iso_utc(),
        "client_id": client_id,
        "account_summary": [],
        "positions": [],
        "open_orders": [],
        "error": last_error or "CONNECTION_FAILED",
    }


def _baseline_status_from_live(live_api: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    baseline = read_json(RECONCILIATION_BASELINE_FILE, {})
    if not isinstance(baseline, dict) or not baseline:
        return {
            "status": "NOT_EVALUATED",
            "severity": "INFO",
            "category": "current_reconciliation_status",
            "generated_at_utc": iso_utc(now),
            "display_reason": "No current post-baseline reconciliation baseline is active",
            "evidence_freshness": "MISSING_BASELINE",
            "blocks_trading": False,
            "fail_closed_recommendation": False,
        }
    baseline_ts = str(baseline.get("baseline_timestamp_utc") or baseline.get("timestamp") or "")
    validation_result = str(baseline.get("baseline_validation_result", "") or "").upper()
    if validation_result not in {"PASSED", "OK"}:
        return {
            "status": "NOT_EVALUATED",
            "severity": "INFO",
            "category": "current_reconciliation_status",
            "generated_at_utc": iso_utc(now),
            "baseline_timestamp_utc": baseline_ts,
            "display_reason": "Current reconciliation baseline is present but not validated",
            "evidence_freshness": "BASELINE_NOT_VALIDATED",
            "blocks_trading": False,
            "fail_closed_recommendation": False,
        }
    if live_api is not None and live_api.get("connected"):
        return {
            "status": "CLEAN",
            "severity": "INFO",
            "category": "current_reconciliation_status",
            "generated_at_utc": live_api.get("timestamp") or iso_utc(now),
            "baseline_timestamp_utc": baseline_ts,
            "source": "IBKR_LIVE_API_POST_BASELINE",
            "display_reason": "Current live IBKR evidence is available after the active reconciliation baseline",
            "evidence_freshness": "FRESH_CURRENT_LIVE_API",
            "positions_count": len(live_api.get("positions", []) or []),
            "open_orders_count": len(live_api.get("open_orders", []) or []),
            "account_summary_rows": len(live_api.get("account_summary", []) or []),
            "blocks_trading": False,
            "fail_closed_recommendation": False,
        }
    return {
        "status": "NOT_EVALUATED",
        "severity": "INFO",
        "category": "current_reconciliation_status",
        "generated_at_utc": iso_utc(now),
        "baseline_timestamp_utc": baseline_ts,
        "source": "POST_BASELINE_RECONCILIATION",
        "display_reason": "Current live IBKR evidence is unavailable for post-baseline reconciliation",
        "evidence_freshness": "CURRENT_EVIDENCE_UNAVAILABLE",
        "blocks_trading": False,
        "fail_closed_recommendation": False,
    }


def reconciliation_status(live_api: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    baseline = read_json(RECONCILIATION_BASELINE_FILE, {})
    baseline_ts = parse_utc((baseline or {}).get("baseline_timestamp_utc")) if isinstance(baseline, dict) else None
    current = read_json(CURRENT_RECONCILIATION_FILE, {})
    if isinstance(current, dict) and current:
        current_ts = parse_utc(current.get("generated_at_utc"))
        if baseline_ts is None or current_ts is None or current_ts >= baseline_ts:
            return current
    return _baseline_status_from_live(live_api, now)


def normalize_reconciliation(recon: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(recon or {})
    status = str(normalized.get("status", "") or "").strip().upper()
    severity = str(normalized.get("severity", "") or "").strip().upper()
    if status == "HISTORICAL_PRE_BASELINE":
        normalized["status"] = "HISTORICAL_PRE_BASELINE"
        normalized["severity"] = "INFO"
        normalized["display_reason"] = "Historical pre-baseline reconciliation evidence is archived for audit only"
        normalized["blocks_trading"] = False
        normalized["fail_closed_recommendation"] = False
        return normalized
    if not status or status == "UNKNOWN":
        normalized["status"] = "NOT_EVALUATED"
        normalized["severity"] = "INFO"
        normalized["display_reason"] = "No current post-baseline reconciliation evidence"
        normalized["blocks_trading"] = False
        return normalized

    reasons_text = ";".join(
        str(normalized.get(name, "") or "")
        for name in ("fail_reasons", "critical_reasons", "warning_reasons")
    )
    reasons = {
        item.strip()
        for chunk in reasons_text.replace(",", ";").split(";")
        for item in [chunk]
        if item.strip()
    }
    evidence_only_reasons = {"latest_ibkr_api_snapshot_not_included"}
    if (
        status == "NOT_CLEAN"
        and reasons
        and reasons.issubset(evidence_only_reasons)
        and not str(normalized.get("api_snapshot_timestamp", "") or "").strip()
        and int(normalized.get("unknown_trade_rows") or 0) == 0
        and int(normalized.get("short_position_rows") or 0) == 0
    ):
        normalized["status"] = "NOT_EVALUATED"
        normalized["severity"] = "INFO"
        normalized["display_reason"] = "Fresh reconciliation evidence unavailable; no confirmed broker/account mismatch"
        normalized["blocks_trading"] = False
        normalized["fail_closed_recommendation"] = False
        return normalized

    normalized["status"] = status
    normalized["severity"] = severity or "INFO"
    normalized["blocks_trading"] = status == "NOT_CLEAN" and normalized["severity"] in {"CRITICAL", "FATAL"}
    return normalized


def _run_text(args: list[str], timeout: float = 3.0) -> str:
    try:
        startupinfo = None
        creationflags = 0
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
            startupinfo.wShowWindow = 0
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        return (result.stdout or "") + (result.stderr or "")
    except Exception:
        return ""


def gateway_processes() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if sys.platform.startswith("win"):
        output = _run_text(["tasklist", "/fo", "csv", "/nh"])
        for line in output.splitlines():
            parts = [part.strip().strip('"') for part in line.split('","')]
            if len(parts) < 2:
                continue
            image = parts[0].lower()
            if image in GATEWAY_PROCESS_NAMES or "ibgateway" in image:
                rows.append({"image": parts[0], "pid": parts[1]})
        return rows

    output = _run_text(["ps", "-eo", "pid=,args="])
    for line in output.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid, args = parts
        lower = args.lower()
        if "ibgateway" in lower:
            rows.append({"image": args, "pid": pid})
    return rows


def port_owner(host: str, port: int) -> dict[str, Any]:
    if not sys.platform.startswith("win"):
        output = _run_text(["ss", "-ltnp"])
        suffix = f":{int(port)}"
        for line in output.splitlines():
            if suffix not in line or "LISTEN" not in line:
                continue
            compact = " ".join(line.split())
            parts = compact.split()
            local_addr = parts[3] if len(parts) > 3 else ""
            pid = ""
            image = ""
            if 'pid=' in line:
                try:
                    pid = line.split('pid=', 1)[1].split(',', 1)[0]
                except Exception:
                    pid = ""
            if 'users:(("' in line:
                try:
                    image = line.split('users:(("', 1)[1].split('"', 1)[0]
                except Exception:
                    image = ""
            image_lower = image.lower()
            process_identified = bool(image_lower)
            expected = (not process_identified) or image_lower in GATEWAY_PROCESS_NAMES or "java" in image_lower or "ibgateway" in image_lower
            return {
                "listening": True,
                "pid": pid,
                "image": image,
                "expected_process": expected,
                "process_identified": process_identified,
                "local_address": local_addr,
            }
        return {"listening": False, "pid": "", "image": "", "expected_process": False, "process_identified": False, "local_address": ""}

    output = _run_text(["netstat", "-ano", "-p", "tcp"])
    suffix = f":{int(port)}"
    for line in output.splitlines():
        compact = " ".join(line.split())
        parts = compact.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local_addr, state, pid = parts[1], parts[3].upper(), parts[-1]
        if state != "LISTENING" or not local_addr.endswith(suffix):
            continue
        if not (
            local_addr.startswith("127.0.0.1")
            or local_addr.startswith("0.0.0.0")
            or local_addr.startswith("[::]")
            or local_addr.startswith("::")
            or local_addr.lower().startswith("localhost")
        ):
            continue
        image = ""
        task = _run_text(["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"])
        task_upper = task.upper()
        if task and "INFO:" not in task_upper and "ERROR" not in task_upper and "ERRORE" not in task_upper:
            image = task.splitlines()[0].split('","')[0].strip().strip('"')
        image_lower = image.lower()
        process_identified = bool(image_lower)
        expected = (not process_identified) or image_lower in GATEWAY_PROCESS_NAMES or "ibgateway" in image_lower
        return {
            "listening": True,
            "pid": pid,
            "image": image,
            "expected_process": expected,
            "process_identified": process_identified,
            "local_address": local_addr,
        }
    return {"listening": False, "pid": "", "image": "", "expected_process": False, "process_identified": False, "local_address": ""}


def socket_reachable(host: str, port: int, timeout_seconds: float = 1.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_seconds):
            return True, "CONNECTED"
    except ConnectionRefusedError:
        return False, "CONNECTION_REFUSED"
    except TimeoutError:
        return False, "NETWORK_TIMEOUT"
    except OSError as error:
        return False, type(error).__name__.upper()


def check_socket(host: str = cfg.HOST, port: int = cfg.PORT, timeout_seconds: float = 2.0) -> dict[str, Any]:
    ok, status = socket_reachable(host, port, timeout_seconds)
    result = {
        "host": host,
        "port": port,
        "socket_reachable": ok,
        "checked_at_utc": iso_utc(),
    }
    if not ok:
        result["error"] = status
    return result


def _state_connected(payload: dict[str, Any]) -> bool | None:
    value = payload.get("connected", payload.get("ib_connected"))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "connected", "1"}:
            return True
        if lowered in {"false", "no", "disconnected", "0"}:
            return False
    return None


def live_connection_state(max_age_seconds: int = 300, now: datetime | None = None) -> tuple[bool | None, str, float | None]:
    now = now or utc_now()
    for name in ("heartbeat.json", "bot_status.json"):
        payload = read_json(STATE_DIR / name, {})
        if not isinstance(payload, dict):
            continue
        ts = parse_utc(payload.get("timestamp"))
        if not ts:
            continue
        age = max(0.0, (now - ts).total_seconds())
        if age > max_age_seconds:
            continue
        connected = _state_connected(payload)
        if connected is not None:
            return connected, name, age
    return None, "", None


def snapshot_freshness(snapshot: dict[str, Any], now: datetime | None = None) -> tuple[str, float | None]:
    now = now or utc_now()
    ts = parse_utc(snapshot.get("snapshot_timestamp_utc") or snapshot.get("timestamp"))
    if not ts:
        return "MISSING", None
    age = max(0.0, (now - ts).total_seconds())
    if age > API_SNAPSHOT_MAX_AGE_SECONDS:
        return "STALE", age
    return "FRESH", age


def reconciliation_evidence_freshness(recon: dict[str, Any], now: datetime | None = None) -> tuple[str, float | None]:
    now = now or utc_now()
    explicit = str(recon.get("evidence_freshness", "") or "").strip().upper()
    if explicit:
        return explicit, None
    ts = parse_utc(recon.get("api_snapshot_timestamp"))
    if not ts:
        return "MISSING_EVIDENCE", None
    age = max(0.0, (now - ts).total_seconds())
    if age > API_SNAPSHOT_MAX_AGE_SECONDS:
        return "STALE_EVIDENCE", age
    return "FRESH", age


def manual_login_likely_from_logs(max_age_hours: int = 24, now: datetime | None = None) -> tuple[bool, str]:
    now = now or utc_now()
    candidates = [
        Path.home() / "Jts" / "launcher.log",
        *((Path.home() / "Jts" / "ibgateway" / "1045").glob("**/LOGS/*")),
    ]
    needles = (
        "security tokens associated with your login credentials have expired",
        "please manually",
        "authorization failed",
        "session expired",
    )
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # Inspect only the tail to avoid expensive broad scans and avoid exposing
        # historical sensitive values.  Returned reason is sanitized.
        tail = text[-200_000:].lower()
        if any(needle in tail for needle in needles):
            try:
                mtime_age = (now - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)).total_seconds()
            except Exception:
                mtime_age = 0
            if mtime_age <= max_age_hours * 3600:
                return True, "recent IB Gateway log reports expired session/security token and manual login requirement"
    return False, ""


def normalize_ib_timezone(timezone_id: Any) -> str:
    mapping = {
        "EST": "America/New_York",
        "EDT": "America/New_York",
        "CST": "America/Chicago",
        "MST": "America/Denver",
        "PST": "America/Los_Angeles",
        "MET": "Europe/Amsterdam",
        "CET": "Europe/Paris",
        "GB-Eire": "Europe/London",
        "GMT": "Europe/London",
        "UTC": "UTC",
    }
    text = str(timezone_id or "").strip()
    return mapping.get(text, text)


def get_zoneinfo(timezone_id: Any):
    try:
        return ZoneInfo(normalize_ib_timezone(timezone_id))
    except Exception:
        return None


def parse_ibkr_hours_segment(segment: str):
    if not segment or "CLOSED" in segment.upper() or "-" not in segment:
        return None
    try:
        start_txt, end_txt = segment.split("-", 1)
        return (
            datetime.strptime(start_txt, "%Y%m%d:%H%M"),
            datetime.strptime(end_txt, "%Y%m%d:%H%M"),
        )
    except Exception:
        return None


def normalize_aware_utc(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_time_for_timezone(value: datetime | None, timezone_id: Any) -> str:
    current = normalize_aware_utc(value)
    if current is None:
        return ""
    tz = get_zoneinfo(timezone_id) or ZoneInfo("America/New_York")
    return current.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def unavailable_market_hours(
    reason: str,
    *,
    source: str = "UNAVAILABLE",
    symbol: str = "",
    timezone_id: str = "",
    time_source: str = "UNAVAILABLE",
) -> dict[str, Any]:
    return {
        "source": source,
        "symbol": symbol,
        "timezone": normalize_ib_timezone(timezone_id) if timezone_id else "",
        "trading_open": None,
        "liquid_open": None,
        "time_source": time_source,
        "trusted_time": False,
        "current_time": "",
        "detail": reason,
        "disabled_reason": reason,
    }


def hours_open(hours_text: Any, timezone_id: Any, now: datetime | None = None) -> bool | None:
    if not hours_text or not timezone_id or now is None:
        return None
    tz = get_zoneinfo(timezone_id)
    if tz is None:
        return None
    current = normalize_aware_utc(now)
    if current is None:
        return None
    now_local = current.astimezone(tz)
    parsed_any = False
    for block in str(hours_text).split(";"):
        for segment in block.split(","):
            parsed = parse_ibkr_hours_segment(segment.strip())
            if parsed is None:
                continue
            parsed_any = True
            start_naive, end_naive = parsed
            start = start_naive.replace(tzinfo=tz)
            end = end_naive.replace(tzinfo=tz)
            if start <= now_local <= end:
                return True
    return False if parsed_any else None


def market_hours_detail(
    *,
    source: str,
    symbol: str = "",
    timezone_id: str = "",
    trading_open: bool | None,
    liquid_open: bool | None,
    now: datetime | None = None,
    time_source: str = "IBKR_SERVER_TIME",
) -> str:
    current = format_time_for_timezone(now, timezone_id)
    if not current:
        return MARKET_HOURS_TIME_UNAVAILABLE_REASON
    subject = f"{symbol} " if symbol else ""
    trading = "OPEN" if trading_open is True else "CLOSED" if trading_open is False else "not confirmed"
    liquid = "IN" if liquid_open is True else "OUT" if liquid_open is False else "not confirmed"
    if liquid_open is False:
        reason = "outside the IBKR liquidHours window"
    elif trading_open is False:
        reason = "outside the IBKR tradingHours window"
    elif liquid_open is True and trading_open is True:
        reason = "inside IBKR tradingHours and liquidHours"
    else:
        reason = "market-hours evidence is incomplete"
    return (
        f"{source}: {subject}tradingHours={trading}, liquidHours={liquid}, "
        f"time={current} ({time_source}); {reason}."
    )


def _stock_from_position(row: dict[str, Any]):
    contract = row.get("contract", {}) if isinstance(row, dict) else {}
    symbol = str(row.get("symbol") or contract.get("symbol") or "").strip().upper()
    currency = str(row.get("currency") or contract.get("currency") or "USD").strip().upper()
    if not symbol or currency != "USD":
        return None
    stock = Stock(symbol, "SMART", currency)
    primary = str(row.get("primaryExchange") or contract.get("primaryExchange") or "").strip()
    if primary:
        stock.primaryExchange = primary
    con_id = row.get("conId") or contract.get("conId")
    try:
        if con_id:
            stock.conId = int(con_id)
    except Exception:
        pass
    return stock


def market_hours_contract_candidates(positions: list[dict[str, Any]]) -> list:
    candidates = [Stock(MARKET_HOURS_CONTRACT_SYMBOL, "SMART", "USD")]
    for row in positions or []:
        stock = _stock_from_position(row)
        if stock is not None:
            candidates.append(stock)
    seen: set[str] = set()
    unique = []
    for contract in candidates:
        key = str(getattr(contract, "conId", "") or getattr(contract, "symbol", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(contract)
    return unique


def collect_ibkr_market_hours(ib: IB, positions: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    current_time = normalize_aware_utc(now)
    for contract in market_hours_contract_candidates(positions):
        symbol = str(getattr(contract, "symbol", "") or MARKET_HOURS_CONTRACT_SYMBOL)
        try:
            with ibkr_request_timeout(ib):
                details_list = ib.reqContractDetails(contract)
        except Exception as error:
            last_error = type(error).__name__
            continue
        if not details_list:
            last_error = "NO_CONTRACT_DETAILS"
            continue
        details = details_list[0]
        timezone_id = str(getattr(details, "timeZoneId", "") or "")
        if current_time is None:
            return unavailable_market_hours(
                MARKET_HOURS_TIME_UNAVAILABLE_REASON,
                source="IBKR_CONTRACT_DETAILS",
                symbol=symbol,
                timezone_id=timezone_id,
                time_source="UNAVAILABLE",
            )
        trading_open = hours_open(getattr(details, "tradingHours", None), timezone_id, current_time)
        liquid_open = hours_open(getattr(details, "liquidHours", None), timezone_id, current_time)
        return {
            "source": "IBKR_CONTRACT_DETAILS",
            "symbol": symbol,
            "timezone": normalize_ib_timezone(timezone_id),
            "trading_open": trading_open,
            "liquid_open": liquid_open,
            "time_source": "IBKR_SERVER_TIME",
            "trusted_time": True,
            "current_time": format_time_for_timezone(current_time, timezone_id),
            "detail": market_hours_detail(
                source="IBKR contractDetails",
                symbol=symbol,
                timezone_id=timezone_id,
                trading_open=trading_open,
                liquid_open=liquid_open,
                now=current_time,
                time_source="IBKR_SERVER_TIME",
            ),
        }
    reason = f"{MARKET_HOURS_SCHEDULE_UNAVAILABLE_REASON}: {locals().get('last_error', 'NO_CANDIDATE')}"
    return unavailable_market_hours(reason, source="UNAVAILABLE")


def market_hours_from_evidence(evidence: dict[str, Any], now: datetime | None = None) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(evidence, dict):
        evidence = unavailable_market_hours(MARKET_HOURS_TIME_UNAVAILABLE_REASON)
    elif not evidence.get("trusted_time") and evidence.get("time_source") != "IBKR_SERVER_TIME":
        evidence = {
            **evidence,
            **unavailable_market_hours(
                evidence.get("disabled_reason")
                or evidence.get("detail")
                or MARKET_HOURS_TIME_UNAVAILABLE_REASON,
                source=str(evidence.get("source") or "UNAVAILABLE"),
                symbol=str(evidence.get("symbol") or ""),
                timezone_id=str(evidence.get("timezone") or ""),
                time_source=str(evidence.get("time_source") or "UNAVAILABLE"),
            ),
        }
    market_status = (
        "OPEN" if evidence.get("trading_open") is True else "CLOSED" if evidence.get("trading_open") is False else "UNAVAILABLE"
    )
    liquid_status = (
        "IN" if evidence.get("liquid_open") is True else "OUT" if evidence.get("liquid_open") is False else "UNAVAILABLE"
    )
    return market_status, liquid_status, evidence


def cached_market_hours_evidence(cached_health: dict[str, Any]) -> dict[str, Any]:
    market_status = str(cached_health.get("market_status", "") or "").upper()
    liquid_status = str(cached_health.get("liquid_hours_status", "") or "").upper()
    time_source = str(cached_health.get("market_hours_time_source", "") or "")
    trading_open = True if market_status == "OPEN" else False if market_status == "CLOSED" else None
    liquid_open = True if liquid_status == "IN" else False if liquid_status == "OUT" else None
    trusted = time_source == "IBKR_SERVER_TIME" and trading_open is not None and liquid_open is not None
    if not trusted:
        return unavailable_market_hours(
            MARKET_HOURS_TIME_UNAVAILABLE_REASON,
            source="LAST_KNOWN_SYSTEM_HEALTH",
            time_source=time_source or "UNAVAILABLE",
        )
    return {
        "source": cached_health.get("market_hours_source") or "LAST_KNOWN_SYSTEM_HEALTH",
        "symbol": cached_health.get("market_hours_symbol") or "",
        "timezone": cached_health.get("market_hours_timezone") or "",
        "trading_open": trading_open,
        "liquid_open": liquid_open,
        "time_source": time_source,
        "trusted_time": True,
        "current_time": cached_health.get("market_hours_current_time") or "",
        "detail": cached_health.get("market_hours_detail") or "Last known fresh IBKR market-hours evidence.",
    }


def _account_value(snapshot: dict[str, Any], tag: str) -> str:
    for row in snapshot.get("account_summary", []) or []:
        if str(row.get("tag", "")).lower() == tag.lower():
            value = str(row.get("value", "") or "")
            currency = str(row.get("currency", "") or "")
            return f"{value} {currency}".strip()
    return ""


def _positions_unrealized_pnl(snapshot: dict[str, Any]) -> str:
    total = 0.0
    found = False
    currency = ""
    for row in snapshot.get("positions", []) or []:
        try:
            total += float(row.get("unrealizedPNL") or row.get("unrealized_pnl"))
            found = True
        except Exception:
            continue
        currency = currency or str(row.get("currency", "") or "")
    return f"{total:.2f} {currency}".strip() if found else ""


def summarize_open_orders(snapshot: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or utc_now()
    rows: list[dict[str, Any]] = []
    for item in snapshot.get("open_orders", []) or []:
        contract = item.get("contract", {}) or {}
        order = item.get("order", {}) or {}
        status = item.get("orderStatus", {}) or {}
        submitted_at = (
            order.get("submitted_at_utc")
            or order.get("submittedAt")
            or item.get("submitted_at_utc")
            or item.get("timestamp_utc")
        )
        submitted_dt = parse_utc(submitted_at)
        age_seconds = max(0.0, (now - submitted_dt).total_seconds()) if submitted_dt else None
        review = age_seconds is None or age_seconds >= ORDER_PENDING_REVIEW_MINUTES * 60
        rows.append(
            {
                "symbol": contract.get("symbol", ""),
                "conId": contract.get("conId", ""),
                "currency": contract.get("currency", ""),
                "exchange": contract.get("exchange", ""),
                "primaryExchange": contract.get("primaryExchange", ""),
                "action": order.get("action", ""),
                "orderType": order.get("orderType", ""),
                "limitPrice": order.get("lmtPrice", ""),
                "quantity": order.get("totalQuantity", ""),
                "filledQuantity": status.get("filled", ""),
                "remainingQuantity": status.get("remaining", ""),
                "orderStatus": status.get("status", ""),
                "orderId": order.get("orderId", ""),
                "permId": order.get("permId", ""),
                "orderAgeSeconds": age_seconds,
                "orderAge": format_age(age_seconds),
                "insideLiquidHours": "UNKNOWN",
                "operatorReviewRecommended": bool(review),
            }
        )
    return rows


def format_age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{hours:02d}h {minutes:02d}m" if hours else f"{minutes:02d}m"


def classify_state(
    *,
    gateway_running: bool,
    owner: dict[str, Any],
    socket_ok: bool,
    live_connected: bool | None,
    snapshot_connected: bool | None,
    recon: dict[str, Any],
    manual_login_likely: bool,
) -> tuple[str, str, str]:
    if not gateway_running:
        return "GATEWAY_PROCESS_ABSENT", "GATEWAY_PROCESS_DEAD", "CRITICAL"
    if not owner.get("listening"):
        if manual_login_likely:
            return "MANUAL_LOGIN_LIKELY", "MANUAL_LOGIN_REQUIRED", "CRITICAL"
        return "API_PORT_CLOSED", "PORT_CLOSED", "ERROR"
    if owner.get("listening") and owner.get("process_identified", True) and not owner.get("expected_process"):
        return "API_PORT_OWNED_BY_WRONG_PROCESS", "PORT_OWNED_BY_WRONG_PROCESS", "CRITICAL"
    if not socket_ok:
        return "API_SOCKET_LISTENING_NOT_READY", "NETWORK_TIMEOUT", "ERROR"
    connected = live_connected
    if connected is False:
        if manual_login_likely:
            return "MANUAL_LOGIN_LIKELY", "MANUAL_LOGIN_REQUIRED", "CRITICAL"
        return "API_NOT_AUTHENTICATED", "API_NOT_AUTHENTICATED", "ERROR"
    if connected is not True:
        return "API_SOCKET_LISTENING_NOT_READY", "UNKNOWN", "WARNING"
    recon = normalize_reconciliation(recon)
    if str(recon.get("status", "")).upper() == "CLEAN" and str(recon.get("severity", "")).upper() not in {"CRITICAL", "FATAL"}:
        return "API_READY_RECONCILED", "NONE", "INFO"
    if not recon.get("blocks_trading"):
        return "API_CONNECTED_OPERATIONAL", "NONE", "INFO"
    return "API_CONNECTED_RECONCILIATION_PENDING", "RECONCILIATION_FAILED", "WARNING"


def collect_system_health(
    now: datetime | None = None,
    *,
    probe_socket: bool = True,
    allow_live_probe: bool = True,
) -> dict[str, Any]:
    now = now or utc_now()
    host = str(getattr(cfg, "HOST", "127.0.0.1"))
    port = int(getattr(cfg, "PORT", 4002))
    processes = gateway_processes()
    owner = port_owner(host, port)
    socket_ok, socket_status = socket_reachable(host, port) if probe_socket else (False, "NOT_PROBED")
    live_connected, live_source, live_age = live_connection_state(now=now)
    live_probe_allowed = abs((utc_now() - now).total_seconds()) <= 3600
    cached_health = cached_system_health(now)
    if socket_ok and live_probe_allowed and allow_live_probe:
        live_api = collect_live_api_evidence(host, port)
    else:
        live_api = {
            "connected": False,
            "account_summary": [],
            "positions": [],
            "open_orders": [],
            "error": "LIVE_PROBE_SKIPPED" if socket_ok else socket_status,
            "timestamp": iso_utc(now),
        }
    live_api_connected = bool(live_api.get("connected"))
    using_cached_live = False
    transient_live_error = str(live_api.get("error", "")).upper() in {
        "MONITORING_CLIENT_BUSY",
        "RUNTIMEERROR",
        "TIMEOUTERROR",
        "LIVE_PROBE_SKIPPED",
    }
    if not live_api_connected and transient_live_error and cached_health.get("portfolio_account_source") in {"LIVE_IB_API", "LAST_KNOWN_LIVE_IB_API"}:
        using_cached_live = True
        live_api_connected = True
        live_api = {
            "connected": True,
            "timestamp": cached_health.get("live_api_timestamp") or cached_health.get("timestamp") or iso_utc(now),
            "client_id": cached_health.get("live_api_client_id") or int(getattr(cfg, "REMOTE_CONTROL_CLIENT_ID", 23)),
            "account_summary": [],
            "positions": cached_health.get("positions", []) or [],
            "open_orders": cached_health.get("open_orders", []) or [],
            "market_hours": cached_market_hours_evidence(cached_health),
            "error": f"LAST_KNOWN_DATA_USED_AFTER_{str(live_api.get('error', 'TRANSIENT_ERROR')).upper()}",
        }
    runtime_data = live_api if live_api_connected else {"account_summary": [], "positions": [], "open_orders": []}
    snapshot_path, snapshot = latest_api_snapshot()
    snapshot_status, snapshot_age = snapshot_freshness(snapshot, now)
    recon = normalize_reconciliation(reconciliation_status(live_api if live_api_connected else None, now))
    recon_evidence_status, recon_evidence_age = reconciliation_evidence_freshness(recon, now)
    if recon.get("status") == "NOT_EVALUATED" and not recon.get("evidence_freshness"):
        recon_evidence_status = "NO_CURRENT_REPORT"
    if recon_evidence_status == "STALE_EVIDENCE" and str(recon.get("severity", "")).upper() in {"CRITICAL", "FATAL"}:
        recon = dict(recon)
        recon["severity"] = "WARNING"
    manual_likely, manual_reason = manual_login_likely_from_logs(now=now)
    gateway_running = bool(processes) or bool(owner.get("listening") and socket_ok and (live_connected is True or live_api_connected))
    runtime_execution = runtime_execution_status(now)
    runtime_health = runtime_execution["runtime_health"]
    automated_orders = automated_order_runtime_summary()
    schedule_status = scheduler_runtime_summary(now)
    broker_snapshot = read_json(cfg.BROKER_SNAPSHOT_FILE, {})
    account_mode = str((broker_snapshot or {}).get("account_mode") or "UNKNOWN")
    cash_value = cached_health.get("cash", "") if using_cached_live else (_account_value(runtime_data, "TotalCashValue") or _account_value(runtime_data, "CashBalance")) if live_api_connected else ""
    buying_power_value = cached_health.get("buying_power", "") if using_cached_live else _account_value(runtime_data, "BuyingPower") if live_api_connected else ""
    net_liquidation_value = cached_health.get("net_liquidation", "") if using_cached_live else _account_value(runtime_data, "NetLiquidation") if live_api_connected else ""
    try:
        investable_capital = evaluate_investable_capital_control(net_liquidation_value) if net_liquidation_value != "" else {}
    except Exception as error:
        investable_capital = {
            "mode": "UNKNOWN",
            "configured_investable_capital": "",
            "effective_investable_capital": "",
            "compliance": "INVALID",
            "reason": type(error).__name__,
        }
    state, recovery_reason, severity = classify_state(
        gateway_running=gateway_running,
        owner=owner,
        socket_ok=socket_ok,
        live_connected=live_connected if live_connected is not None else (True if live_api_connected else None),
        snapshot_connected=None,
        recon=recon,
        manual_login_likely=manual_likely,
    )
    state, recovery_reason, severity = apply_runtime_health_override(
        state,
        recovery_reason,
        severity,
        runtime_health,
    )
    current_manual_login = state in {"MANUAL_LOGIN_LIKELY", "FAIL_CLOSED_MANUAL_INTERVENTION_REQUIRED"}
    gateway_auth_event_status = "CURRENT" if current_manual_login else "RESOLVED" if manual_likely else ""
    gateway_auth_event_detail = (
        manual_reason
        if current_manual_login
        else "Historical Gateway authentication event resolved by current live API authentication"
        if manual_likely
        else ""
    )
    market_evidence = live_api.get("market_hours") if live_api_connected else {}
    market_status, liquid_hours, market_evidence = market_hours_from_evidence(market_evidence, now)
    execute_orders_enabled, execute_orders_source = runtime_execute_orders()
    disabled_reasons: list[str] = []
    if runtime_execution["runtime_process"] != "RUNNING":
        disabled_reasons.append("BOT NOT RUNNING")
    if not execute_orders_enabled:
        if execute_orders_source == "runtime_health":
            disabled_reasons.append(runtime_health.get("reason") or "Runtime health disabled trading")
        elif execute_orders_source == "activation_preflight":
            activation = read_json(cfg.STATE_DIR / "automated_activation_preflight.json", {})
            disabled_reasons.append("Activation preflight failed: " + "; ".join(activation.get("issues", []) or []))
        else:
            disabled_reasons.append("Configuration disabled")
    if str(runtime_health.get("strategy_engine_state", "")).upper() == "FAILED":
        disabled_reasons.append("Strategy engine failed")
    if str(runtime_health.get("order_engine_state", "")).upper() == "FAILED":
        disabled_reasons.append("Order engine failed")
    if str(runtime_health.get("startup_reconciliation_state", "")).upper() == "FAILED":
        disabled_reasons.append("Startup reconciliation failed")
    if str(investable_capital.get("compliance", "") or "").upper() != "OK":
        disabled_reasons.append(investable_capital.get("reason") or "Investable capital compliance failed")
    if market_status == "UNAVAILABLE" or liquid_hours == "UNAVAILABLE":
        disabled_reasons.append(market_evidence.get("disabled_reason") or market_evidence.get("detail") or MARKET_HOURS_TIME_UNAVAILABLE_REASON)
    else:
        if market_status != "OPEN":
            disabled_reasons.append("Market Closed")
        if liquid_hours != "IN":
            disabled_reasons.append("Outside Liquid Hours")
    if state not in {"API_READY_RECONCILED", "API_CONNECTED_OPERATIONAL"}:
        if state == "MANUAL_LOGIN_LIKELY":
            disabled_reasons.append("Manual login likely required")
        elif state == "API_NOT_AUTHENTICATED":
            disabled_reasons.append("API not authenticated")
        elif state == "API_CONNECTED_RECONCILIATION_PENDING":
            if recon_evidence_status == "STALE_EVIDENCE":
                disabled_reasons.append("Reconciliation stale evidence")
            else:
                disabled_reasons.append("Reconciliation pending")
        elif state == "TRADING_BLOCKED":
            pass
        else:
            disabled_reasons.append("Gateway not ready")
    elif recon.get("blocks_trading"):
        disabled_reasons.append("Reconciliation failed")
    open_orders = summarize_open_orders(runtime_data, now)
    oldest_age = max((row["orderAgeSeconds"] for row in open_orders if row.get("orderAgeSeconds") is not None), default=None)
    manual_intervention = state in {"MANUAL_LOGIN_LIKELY", "FAIL_CLOSED_MANUAL_INTERVENTION_REQUIRED"} or severity in {"CRITICAL", "FATAL"}
    trading_enabled = not disabled_reasons
    return {
        "timestamp": iso_utc(now),
        "gateway_process_status": "RUNNING" if gateway_running else "ABSENT",
        "gateway_processes": processes,
        "api_port_status": "LISTENING" if owner.get("listening") else "CLOSED",
        "api_port_owner": owner,
        "api_socket_status": socket_status,
        "api_handshake_authentication_status": "CONNECTED" if (live_api_connected or live_connected is True) else "DISCONNECTED" if live_connected is False else "UNKNOWN",
        "live_api_status": "CONNECTED_LAST_KNOWN" if using_cached_live else "CONNECTED" if live_api_connected else "DISCONNECTED",
        "live_api_error": live_api.get("error", ""),
        "live_api_timestamp": live_api.get("timestamp", ""),
        "live_api_client_id": live_api.get("client_id", ""),
        "bot_connection_status": "CONNECTED" if live_connected is True else "DISCONNECTED" if live_connected is False else "UNKNOWN",
        "bot_connection_source": live_source,
        "bot_connection_age_seconds": live_age,
        "reconciliation_status": recon.get("status", "NOT_EVALUATED"),
        "reconciliation_severity": recon.get("severity", "INFO"),
        "reconciliation_display_reason": recon.get("display_reason", ""),
        "reconciliation_evidence_freshness": recon_evidence_status,
        "reconciliation_api_snapshot_age_seconds": recon_evidence_age,
        "reconciliation_baseline_timestamp": recon.get("baseline_timestamp_utc", ""),
        "market_status": market_status,
        "liquid_hours_status": liquid_hours,
        "market_hours_source": market_evidence.get("source", ""),
        "market_hours_symbol": market_evidence.get("symbol", ""),
        "market_hours_timezone": market_evidence.get("timezone", ""),
        "market_hours_time_source": market_evidence.get("time_source", ""),
        "market_hours_current_time": market_evidence.get("current_time", ""),
        "market_hours_pc_time_diagnostic": format_time_for_timezone(utc_now(), "America/New_York"),
        "market_hours_detail": market_evidence.get("detail", ""),
        "order_execution_enabled": execute_orders_enabled,
        "order_execution_source": execute_orders_source,
        "automated_trading_enabled": bool(execute_orders_enabled),
        "automated_execution_switch": cfg.AUTOMATED_PAPER_EXECUTION_SWITCH,
        "account_mode": account_mode,
        "investable_capital_mode": investable_capital.get("mode", "UNKNOWN"),
        "configured_investable_capital": investable_capital.get("configured_investable_capital", ""),
        "effective_investable_capital": investable_capital.get("effective_investable_capital", ""),
        "investable_capital_compliance": investable_capital.get("compliance", "UNKNOWN"),
        "investable_capital_reason": investable_capital.get("reason", ""),
        "next_strategy_cycle": schedule_status.get("next_strategy_cycle_utc", ""),
        "scheduler_cycle_time_et": schedule_status.get("cycle_time_et", ""),
        "scheduler_cycle_timezone": schedule_status.get("timezone", ""),
        "last_order_submission": automated_orders.get("last_order_submission", "none"),
        "open_automated_orders": automated_orders.get("open_automated_orders", 0),
        "automated_order_count": automated_orders.get("orders_count", 0),
        "last_reconciliation_result": recon.get("status", "NOT_EVALUATED"),
        "runtime_process": runtime_execution["runtime_process"],
        "runtime_pid": runtime_execution["runtime_pid"],
        "runtime_process_alive": runtime_execution["runtime_process"] == "RUNNING",
        "bot_status": runtime_execution["bot_status"],
        "bot_status_file_status": runtime_execution["bot_status_file_status"],
        "bot_not_running": runtime_execution["bot_not_running"],
        "scheduler_status": runtime_execution["scheduler"],
        "scheduler_pid": runtime_execution["scheduler_pid"],
        "last_heartbeat_timestamp": runtime_execution["last_heartbeat_timestamp"],
        "last_heartbeat_age": runtime_execution["last_heartbeat_age"],
        "last_strategy_cycle": runtime_execution["last_strategy_cycle"],
        "last_cycle_time": runtime_execution["last_cycle_time"],
        "runtime_strategy_engine_state": runtime_execution["strategy_engine"],
        "runtime_order_engine_state": runtime_health.get("order_engine_state", ""),
        "runtime_startup_reconciliation_state": runtime_health.get("startup_reconciliation_state", ""),
        "runtime_trading_state": runtime_health.get("trading_state", ""),
        "runtime_health_reason": runtime_health.get("reason", ""),
        "trading_enabled": trading_enabled,
        "reason_trading_disabled": "; ".join(disabled_reasons) if disabled_reasons else "",
        "system_state": state,
        "recovery_reason": recovery_reason,
        "recovery_detail": manual_reason if current_manual_login else "",
        "gateway_auth_event_status": gateway_auth_event_status,
        "gateway_auth_event_detail": gateway_auth_event_detail,
        "severity": severity,
        "open_positions_count": len(runtime_data.get("positions", []) or []) if live_api_connected else None,
        "open_orders_count": len(open_orders) if live_api_connected else None,
        "cash": cash_value,
        "buying_power": buying_power_value,
        "net_liquidation": net_liquidation_value,
        "unrealized_pnl": cached_health.get("unrealized_pnl", "") if using_cached_live else _positions_unrealized_pnl(runtime_data) if live_api_connected else "",
        "portfolio_account_source": "LAST_KNOWN_LIVE_IB_API" if using_cached_live else "LIVE_IB_API" if live_api_connected else "NOT_REFRESHED",
        "oldest_open_order_age_seconds": oldest_age,
        "oldest_open_order_age": (
            "none" if live_api_connected and not open_orders else format_age(oldest_age) if live_api_connected else "not refreshed"
        ),
        "open_orders": open_orders,
        "positions": runtime_data.get("positions", []) if live_api_connected else [],
        "last_successful_api_ready_timestamp": live_api.get("timestamp", "") if live_api_connected else "",
        "api_snapshot_freshness": snapshot_status,
        "api_snapshot_age_seconds": snapshot_age,
        "api_snapshot_timestamp": snapshot.get("snapshot_timestamp_utc", ""),
        "last_successful_reconciliation_timestamp": recon.get("generated_at_utc", ""),
        "manual_intervention_required": manual_intervention,
        "snapshot_file": str(snapshot_path) if snapshot_path else "",
        "snapshot_usage": "DIAGNOSTIC_ONLY",
        "reconciliation_blocks_trading": bool(recon.get("blocks_trading")),
    }


def write_system_health(now: datetime | None = None, *, allow_live_probe: bool = True) -> dict[str, Any]:
    health = collect_system_health(now, allow_live_probe=allow_live_probe)
    try:
        atomic_write_json(SYSTEM_HEALTH_FILE, health)
    except OSError:
        pass
    return health


def _status_value(value: Any, fallback: str = "not refreshed") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _count_value(value: Any, fallback: str = "not refreshed") -> str:
    return fallback if value is None else str(value)


def _reconciliation_is_actionable(health: dict[str, Any]) -> bool:
    status = str(health.get("reconciliation_status", "") or "").upper()
    severity = str(health.get("reconciliation_severity", "") or "").upper()
    evidence = str(health.get("reconciliation_evidence_freshness", "") or "").upper()
    if health.get("reconciliation_blocks_trading"):
        return True
    if severity in {"WARNING", "CRITICAL", "FATAL"}:
        return True
    if status == "CLEAN" and evidence in {"FRESH", "FRESH_CURRENT_LIVE_API"}:
        return True
    return False


def format_status_lines(health: dict[str, Any]) -> list[str]:
    bot_status = _status_value(health.get("bot_status"), "STOPPED")
    lines = [
        "SYSTEM STATUS",
        f"Gateway ............. {_status_value(health.get('gateway_process_status'), 'not checked')}",
        f"API ................. {_status_value(health.get('api_socket_status'), 'not checked')}",
        f"Authentication ...... {_status_value(health.get('api_handshake_authentication_status'), 'not checked')}",
        f"Live API Data ....... {_status_value(health.get('live_api_status'), 'not refreshed')}",
        "",
        f"Runtime Process ..... {_status_value(health.get('runtime_process'), 'STOPPED')}",
        f"Bot Status .......... {bot_status}",
        *(["BOT NOT RUNNING"] if health.get("bot_not_running") else []),
        f"Strategy Engine ..... {_status_value(health.get('runtime_strategy_engine_state'), 'not checked')}",
        f"Scheduler ........... {_status_value(health.get('scheduler_status'), 'STOPPED')}",
        f"Last Heartbeat ...... {_status_value(health.get('last_heartbeat_timestamp'), 'missing')} ({_status_value(health.get('last_heartbeat_age'), 'age unknown')})",
        f"Last Strategy Cycle . {_status_value(health.get('last_strategy_cycle'), 'not checked')}",
        f"Last Cycle Time ..... {_status_value(health.get('last_cycle_time'), 'not checked')}",
        "",
        f"Trading Enabled ..... {'YES' if health.get('trading_enabled') else 'NO'}",
        f"Reason .............. {health.get('reason_trading_disabled') or 'None'}",
        f"Automated Trading ... {'ENABLED' if health.get('automated_trading_enabled') else 'DISABLED'}",
        f"Account Mode ........ {_status_value(health.get('account_mode'), 'UNKNOWN')}",
        f"Investable Mode ..... {_status_value(health.get('investable_capital_mode'), 'UNKNOWN')}",
        f"Configured IC ....... {_status_value(health.get('configured_investable_capital'), 'not available')}",
        f"Effective IC ........ {_status_value(health.get('effective_investable_capital'), 'not available')}",
        f"IC Compliance ....... {_status_value(health.get('investable_capital_compliance'), 'UNKNOWN')}",
        *(
            [f"IC Reason ........... {health.get('investable_capital_reason')}"]
            if health.get("investable_capital_reason")
            else []
        ),
        f"Next Strategy Cycle . {_status_value(health.get('next_strategy_cycle'), 'not scheduled')}",
        f"Last Order Submission {_status_value(health.get('last_order_submission'), 'none')}",
        f"Open Automated Orders {health.get('open_automated_orders', 0)}",
        f"Last Reconciliation . {_status_value(health.get('last_successful_reconciliation_timestamp'), 'no current report')} / {_status_value(health.get('last_reconciliation_result'), 'not evaluated')}",
        "",
        f"Market .............. {_status_value(health.get('market_status'), 'not checked')}",
        f"Liquid Hours ........ {_status_value(health.get('liquid_hours_status'), 'not checked')}",
        *(
            [f"Market Time Source . {health.get('market_hours_time_source')}"]
            if health.get("market_hours_time_source")
            else []
        ),
        *(
            [f"Market Time ......... {health.get('market_hours_current_time')}"]
            if health.get("market_hours_current_time")
            else []
        ),
        *(
            [f"Market Detail ....... {health.get('market_hours_detail')}"]
            if health.get("market_hours_detail")
            and (health.get("market_status") != "OPEN" or health.get("liquid_hours_status") != "IN")
            else []
        ),
        *(
            [
                f"Order Engine ........ {_status_value(health.get('runtime_order_engine_state'), 'not checked')}",
                f"Startup Reconcile ... {_status_value(health.get('runtime_startup_reconciliation_state'), 'not checked')}",
            ]
        ),
        "",
        f"Portfolio Positions . {_count_value(health.get('open_positions_count'))}",
        f"Portfolio Source .... {_status_value(health.get('portfolio_account_source'), 'not refreshed')}",
        f"NAV ................. {_status_value(health.get('net_liquidation'))}",
        f"Cash ................ {_status_value(health.get('cash'))}",
        f"Buying Power ........ {_status_value(health.get('buying_power'))}",
        f"Open Orders ......... {_count_value(health.get('open_orders_count'))}",
        f"Oldest Open Order ... {_status_value(health.get('oldest_open_order_age'))}",
        "",
        f"System State ........ {_status_value(health.get('system_state'), 'not checked')}",
        f"Recovery Reason ..... {_status_value(health.get('recovery_reason'), 'not checked')}",
        f"Severity ............ {_status_value(health.get('severity'), 'not checked')}",
        "",
        f"Last API Ready ...... {_status_value(health.get('last_successful_api_ready_timestamp'))}",
        f"API Snapshot ........ {_status_value(health.get('api_snapshot_freshness'), 'not available')} (DIAGNOSTIC ONLY)",
        f"Snapshot Usage ...... {_status_value(health.get('snapshot_usage'), 'DIAGNOSTIC_ONLY')}",
    ]
    lines.extend(
        [
            f"Reconciliation ...... {_status_value(health.get('reconciliation_status'), 'not evaluated')} / {_status_value(health.get('reconciliation_severity'), 'INFO')}",
            f"Recon Evidence ...... {_status_value(health.get('reconciliation_evidence_freshness'), 'no current report')}",
            f"Last Reconciliation . {_status_value(health.get('last_successful_reconciliation_timestamp'), 'no current report')}",
        ]
    )
    return lines
