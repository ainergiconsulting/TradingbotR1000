"""First-three-session automated PAPER trading quality monitoring."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import config as cfg
from automated_order_store import load_store
from monitoring_io import atomic_write_json, utc_timestamp


NY_TZ = ZoneInfo(cfg.STRATEGY_CYCLE_TIMEZONE)


def _read_json(path: Path, default: Any) -> Any:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default
    return data


def _safe_name(value: Any) -> str:
    text = str(value or "").replace(":", "").replace("-", "").replace(".", "")
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in text)[:80] or "cycle"


def _parse_utc(value: Any) -> datetime:
    text = str(value or utc_timestamp())
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _session_date(scan: dict[str, Any]) -> str:
    return _parse_utc(scan.get("timestamp_utc")).astimezone(NY_TZ).date().isoformat()


def load_state() -> dict[str, Any]:
    default = {
        "bot": cfg.BOT_NAME,
        "enabled_at_utc": "",
        "session_limit": cfg.QUALITY_MONITOR_SESSION_LIMIT,
        "sessions": [],
    }
    data = _read_json(cfg.QUALITY_MONITOR_STATE_FILE, default)
    if not isinstance(data, dict):
        return default
    data.setdefault("bot", cfg.BOT_NAME)
    data.setdefault("enabled_at_utc", "")
    data.setdefault("session_limit", cfg.QUALITY_MONITOR_SESSION_LIMIT)
    data.setdefault("sessions", [])
    return data


def activate_monitoring() -> dict[str, Any]:
    state = load_state()
    if not state.get("enabled_at_utc"):
        state["enabled_at_utc"] = utc_timestamp()
    state["session_limit"] = cfg.QUALITY_MONITOR_SESSION_LIMIT
    state["updated_at_utc"] = utc_timestamp()
    atomic_write_json(cfg.QUALITY_MONITOR_STATE_FILE, state)
    cfg.QUALITY_MONITOR_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return state


def _monitoring_active_for_session(state: dict[str, Any], session_date: str) -> bool:
    sessions = [str(row.get("session_date") or "") for row in state.get("sessions", []) if isinstance(row, dict)]
    if session_date in sessions:
        return True
    return len(sessions) < int(state.get("session_limit") or cfg.QUALITY_MONITOR_SESSION_LIMIT)


def _upsert_session(state: dict[str, Any], session_date: str, report_path: Path) -> dict[str, Any]:
    sessions = [row for row in state.get("sessions", []) if isinstance(row, dict)]
    for row in sessions:
        if row.get("session_date") == session_date:
            row["report_path"] = str(report_path)
            row["updated_at_utc"] = utc_timestamp()
            break
    else:
        sessions.append(
            {
                "session_date": session_date,
                "started_at_utc": utc_timestamp(),
                "updated_at_utc": utc_timestamp(),
                "report_path": str(report_path),
            }
        )
    state["sessions"] = sessions[: int(state.get("session_limit") or cfg.QUALITY_MONITOR_SESSION_LIMIT)]
    if not state.get("enabled_at_utc"):
        state["enabled_at_utc"] = utc_timestamp()
    state["updated_at_utc"] = utc_timestamp()
    atomic_write_json(cfg.QUALITY_MONITOR_STATE_FILE, state)
    return state


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _order_line(intent: dict[str, Any], execution_report: dict[str, Any]) -> str:
    submitted = {
        (row.get("symbol"), row.get("side")): row
        for row in execution_report.get("submitted_orders", []) or []
    }
    rejected = {
        (row.get("symbol"), row.get("side")): row
        for row in execution_report.get("rejected_orders", []) or []
    }
    duplicate = {
        (row.get("symbol"), row.get("side")): row
        for row in execution_report.get("duplicate_preventions", []) or []
    }
    key = (intent.get("symbol"), intent.get("side"))
    broker = submitted.get(key) or rejected.get(key) or duplicate.get(key) or {}
    result = broker.get("broker_status") or broker.get("reason") or "NotTransmitted"
    return (
        f"| {intent.get('symbol')} | {intent.get('side')} | {intent.get('quantity')} | "
        f"{intent.get('order_type')} | {intent.get('limit_price') or ''} | "
        f"{intent.get('reason') or ''} | {result} | {broker.get('ibkr_order_id') or ''} | "
        f"{broker.get('perm_id') or ''} |"
    )


def _write_markdown_report(session_path: Path, session_payload: dict[str, Any]) -> None:
    cycles = session_payload.get("cycles", []) or []
    lines = [
        f"# TradingbotR1000 Automated PAPER Quality Report - {session_payload['session_date']}",
        "",
        f"Generated: {utc_timestamp()}",
        f"Cycles recorded: {len(cycles)}",
        "",
    ]
    for cycle in cycles:
        scan = cycle.get("scan", {})
        execution = cycle.get("automated_execution_report", {})
        reconciliation = cycle.get("reconciliation", {})
        account_values = scan.get("live_account", {}).get("account_values", {})
        capital = scan.get("investable_capital_control", {})
        lines.extend(
            [
                f"## Cycle {scan.get('cycle_id')}",
                "",
                f"- Timestamp UTC: {scan.get('timestamp_utc')}",
                f"- Effective configuration hash: {scan.get('configuration_sha256')}",
                f"- NLV: {_money(account_values.get('net_liquidation'))}",
                f"- Cash: {_money(account_values.get('cash'))}",
                f"- Buying power: {_money(account_values.get('buying_power'))}",
                f"- Investable capital mode: {capital.get('mode')}",
                f"- Effective investable capital: {_money(capital.get('effective_investable_capital'))}",
                f"- Universe size: {scan.get('universe_expected_symbols')}",
                f"- Market data latest date: {scan.get('market_data_latest_date')}",
                f"- BUY signals: {len(scan.get('selected_candidates') or [])}",
                f"- SELL signals: {len(scan.get('exit_signals') or [])}",
                f"- Rejected symbols/candidates: {len(scan.get('rejected_symbols') or []) + len(scan.get('skipped_candidates') or [])}",
                f"- Planned orders: {len(execution.get('intended_orders') or [])}",
                f"- Submitted orders: {len(execution.get('submitted_orders') or [])}",
                f"- Duplicate preventions: {len(execution.get('duplicate_preventions') or [])}",
                f"- Reconciliation: {reconciliation.get('status', 'not run')}",
                "",
                "| Symbol | Side | Qty | Type | Limit | Decision reason | Broker result | Order ID | Perm ID |",
                "| --- | --- | ---: | --- | ---: | --- | --- | --- | --- |",
            ]
        )
        for intent in execution.get("intended_orders", []) or []:
            lines.append(_order_line(intent, execution))
        if not execution.get("intended_orders"):
            lines.append("| none |  |  |  |  |  |  |  |  |")
        lines.extend(
            [
                "",
                "Review flags:",
                f"- Incorrect or unexplained BUY/SELL decisions: {cycle.get('decision_discrepancies', 'none detected by runtime')}",
                f"- Sizing discrepancies: {cycle.get('sizing_discrepancies', 'none detected by runtime')}",
                f"- Stale or missing data: {cycle.get('market_data_discrepancies', 'none detected by runtime')}",
                f"- Duplicate or omitted orders: {cycle.get('duplicate_or_omitted_orders', 'none detected by runtime')}",
                f"- Local/IBKR differences: {cycle.get('reconciliation_discrepancies', 'see reconciliation result')}",
                f"- Scheduling failures: {cycle.get('scheduling_failures', 'none detected by runtime')}",
                f"- Rejected or partially filled orders: {cycle.get('broker_exceptions', 'see broker result table')}",
                f"- Restart-related failures: {cycle.get('restart_failures', 'none detected by runtime')}",
                "",
            ]
        )
    session_path.write_text("\n".join(lines), encoding="utf-8")


def record_cycle(
    *,
    scan: dict[str, Any],
    automated_execution_report: dict[str, Any],
    broker_before: dict[str, Any],
    broker_after: dict[str, Any],
    reconciliation: dict[str, Any],
    scheduler_trigger_time_utc: str = "",
) -> dict[str, Any] | None:
    if not cfg.EXECUTE_ORDERS:
        return None
    cfg.QUALITY_MONITOR_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    session_date = _session_date(scan)
    state = load_state()
    if not _monitoring_active_for_session(state, session_date):
        return None

    cycle_id = str(scan.get("cycle_id") or utc_timestamp())
    cycle_file = cfg.QUALITY_MONITOR_REPORTS_DIR / f"cycle_{session_date}_{_safe_name(cycle_id)}.json"
    session_file = cfg.QUALITY_MONITOR_REPORTS_DIR / f"session_{session_date}.json"
    session_report = cfg.QUALITY_MONITOR_REPORTS_DIR / f"session_{session_date}_report.md"
    cycle_payload = {
        "bot": cfg.BOT_NAME,
        "recorded_at_utc": utc_timestamp(),
        "session_date": session_date,
        "scheduler_trigger_time_utc": scheduler_trigger_time_utc,
        "scan": scan,
        "automated_execution_report": automated_execution_report,
        "broker_before": broker_before,
        "broker_after": broker_after,
        "reconciliation": reconciliation,
        "automated_order_store": load_store(),
        "decision_discrepancies": "",
        "sizing_discrepancies": "",
        "market_data_discrepancies": "",
        "duplicate_or_omitted_orders": "",
        "reconciliation_discrepancies": "",
        "scheduling_failures": "",
        "broker_exceptions": "",
        "restart_failures": "",
    }
    atomic_write_json(cycle_file, cycle_payload)

    session_payload = _read_json(
        session_file,
        {
            "bot": cfg.BOT_NAME,
            "session_date": session_date,
            "created_at_utc": utc_timestamp(),
            "cycles": [],
        },
    )
    cycles = [row for row in session_payload.get("cycles", []) if row.get("scan", {}).get("cycle_id") != cycle_id]
    cycles.append(cycle_payload)
    session_payload["cycles"] = cycles
    session_payload["updated_at_utc"] = utc_timestamp()
    atomic_write_json(session_file, session_payload)
    _write_markdown_report(session_report, session_payload)
    _upsert_session(state, session_date, session_report)
    return {
        "session_date": session_date,
        "cycle_file": str(cycle_file),
        "session_file": str(session_file),
        "session_report": str(session_report),
    }
