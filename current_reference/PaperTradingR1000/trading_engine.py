"""TradingbotR1000 daily scan and order-plan engine.

The engine orchestrates the approved strategy rules without adding filters or
provider-specific trading assumptions. It is dry-run/order-plan oriented by
default; broker order submission is intentionally outside this pure planning
path and remains gated by runtime safety configuration.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Any
from zoneinfo import ZoneInfo

from automated_broker import AutomatedBrokerError, process_order_plan
import config as cfg
from config_loader import ConfigError, ensure_runtime_ready, load_universe_config
from control_utils import read_blocked_symbols, read_ignored_symbols, stop_bot_requested
from heartbeat_utils import write_heartbeat
from investable_capital_control import evaluate as evaluate_investable_capital_control
from live_account import LiveAccountError, calculate_operational_buy_budget, collect_live_account_context
from logger_utils import log
from monitoring_io import atomic_write_json, utc_timestamp
from quality_monitor import record_cycle as record_quality_monitor_cycle
from reconciliation import reconcile_local_state
from runtime_health import HEALTH_FAILED, HEALTH_OK, HEALTH_STARTING, write_runtime_health
from startup_rebuild import rebuild_and_save
from state_store import (
    active_position_count,
    active_position_symbols,
    load_state,
    pending_buy_count,
    pending_buy_symbols,
    record_daily_scan,
)
from strategy import (
    APPROVED_PARAMETERS,
    EntryEvaluation,
    STRATEGY_VERSION,
    available_slots,
    build_buy_order_plan,
    evaluate_entry_candidate,
    exit_decision,
    investable_capital_value,
    latest_rsi_cross_values,
    liquidity_reserve_value,
    select_candidates,
)
try:
    from .symbol_mapping import canonical_symbol as normalize_symbol, exclusion_reason
except ImportError:  # pragma: no cover - supports direct script execution.
    from symbol_mapping import canonical_symbol as normalize_symbol, exclusion_reason


class EngineInputError(ValueError):
    pass


def _resolve_project_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return cfg.PROJECT_ROOT / path

def load_universe_symbol_records(path: Path, symbol_column: str = "symbol") -> dict[str, list[Any]]:
    if not path.exists():
        raise EngineInputError(f"universe source missing:{path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.reader(handle))
    header_index = None
    for index, row in enumerate(raw_rows):
        if symbol_column in [cell.strip() for cell in row]:
            header_index = index
            break
    if header_index is None:
        raise EngineInputError(f"universe source missing column:{symbol_column}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for _ in range(header_index):
            next(handle)
        reader = csv.DictReader(handle)
        if not reader.fieldnames or symbol_column not in reader.fieldnames:
            raise EngineInputError(f"universe source missing column:{symbol_column}")
        symbols = []
        exclusions = []
        for row in reader:
            asset_class = str(row.get("Asset Class", "")).strip().lower()
            if asset_class and asset_class != "equity":
                continue
            currency = str(row.get("Currency", "") or row.get("Market Currency", "")).strip().upper()
            if currency and currency != "USD":
                continue
            symbol = normalize_symbol(row.get(symbol_column, ""))
            reason = exclusion_reason(symbol)
            if symbol and reason:
                exclusions.append({"symbol": symbol, "source_symbol": str(row.get(symbol_column, "")).strip(), "reason": reason})
                continue
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    if not symbols:
        raise EngineInputError("universe source contains no symbols")
    return {"symbols": symbols, "exclusions": exclusions}


def load_universe_symbols(path: Path, symbol_column: str = "symbol") -> list[str]:
    return list(load_universe_symbol_records(path, symbol_column)["symbols"])


def _canonical_set(symbols: set[str] | None) -> set[str]:
    return {normalize_symbol(symbol) for symbol in symbols or set() if normalize_symbol(symbol)}


def load_completed_closes(path: Path) -> list[float]:
    if not path.exists():
        raise EngineInputError(f"daily bars file missing:{path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "close" not in reader.fieldnames:
            raise EngineInputError(f"daily bars missing close column:{path}")
        closes = []
        for row in reader:
            value = str(row.get("close", "")).strip()
            if value:
                closes.append(float(value))
    return closes


def load_daily_closes(symbols: Iterable[str], daily_bars_dir: Path) -> dict[str, list[float]]:
    bars: dict[str, list[float]] = {}
    for symbol in symbols:
        path = daily_bars_dir / f"{symbol}.csv"
        if path.exists():
            bars[symbol] = load_completed_closes(path)
    return bars


def load_daily_bar_data(symbols: Iterable[str], daily_bars_dir: Path) -> dict[str, Any]:
    closes_by_symbol: dict[str, list[float]] = {}
    signal_dates: dict[str, str] = {}
    status_rows: list[dict[str, Any]] = []
    latest_date = ""
    latest_mtime = 0.0
    for symbol in symbols:
        path = daily_bars_dir / f"{symbol}.csv"
        if not path.exists():
            status_rows.append({"symbol": symbol, "status": "excluded", "reason": "missing_market_data", "path": str(path)})
            continue
        rows = 0
        closes: list[float] = []
        dates: list[str] = []
        duplicates = 0
        invalid = 0
        seen_dates: set[str] = set()
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                required = {"date", "open", "high", "low", "close", "volume"}
                if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                    status_rows.append({"symbol": symbol, "status": "excluded", "reason": "invalid_market_data_schema", "path": str(path)})
                    continue
                for row in reader:
                    date = str(row.get("date", "")).strip()
                    close_text = str(row.get("close", "")).strip()
                    if date in seen_dates:
                        duplicates += 1
                    seen_dates.add(date)
                    try:
                        close = float(close_text)
                    except ValueError:
                        invalid += 1
                        continue
                    if not date or close <= 0:
                        invalid += 1
                        continue
                    rows += 1
                    dates.append(date)
                    closes.append(close)
        except Exception as exc:
            status_rows.append({"symbol": symbol, "status": "excluded", "reason": f"market_data_read_error:{type(exc).__name__}", "path": str(path)})
            continue
        if duplicates or invalid or not closes:
            status_rows.append(
                {
                    "symbol": symbol,
                    "status": "excluded",
                    "reason": "invalid_market_data_rows",
                    "duplicates": duplicates,
                    "invalid_rows": invalid,
                    "rows": rows,
                    "path": str(path),
                }
            )
            continue
        last_date = dates[-1]
        latest_date = max(latest_date, last_date)
        latest_mtime = max(latest_mtime, path.stat().st_mtime)
        closes_by_symbol[symbol] = closes
        signal_dates[symbol] = last_date
        status_rows.append(
            {
                "symbol": symbol,
                "status": "loaded",
                "reason": "",
                "rows": rows,
                "first_date": dates[0],
                "last_date": last_date,
                "path": str(path),
            }
        )
    if latest_date:
        for row in status_rows:
            if row.get("status") == "loaded" and row.get("last_date") != latest_date:
                row["status"] = "excluded"
                row["reason"] = "stale_market_data"
                closes_by_symbol.pop(str(row["symbol"]), None)
                signal_dates.pop(str(row["symbol"]), None)
    return {
        "closes_by_symbol": closes_by_symbol,
        "signal_dates": signal_dates,
        "status_rows": status_rows,
        "latest_date": latest_date,
        "timestamp_utc": datetime.fromtimestamp(latest_mtime, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        if latest_mtime
        else "",
    }


def expected_latest_completed_weekday(now_utc: datetime | None = None) -> str:
    """Return the strict prior weekday expected at the 09:28 ET scan.

    This is deliberately fail-closed. A market holiday on the immediately
    preceding weekday will require fresh-data confirmation rather than allowing
    an older dataset to trade silently.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    current_et_date = now_utc.astimezone(ZoneInfo("America/New_York")).date()
    expected = current_et_date - timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    return expected.strftime("%Y%m%d")


def _serialize_evaluation(item: EntryEvaluation) -> dict[str, Any]:
    return asdict(item) | {"is_candidate": item.is_candidate}


def scan_from_closes(
    closes_by_symbol: dict[str, list[float]],
    *,
    net_liquidation_value: float | None = None,
    open_positions: int,
    pending_buy_orders: int = 0,
    active_symbols: set[str] | None = None,
    pending_buy_symbols: set[str] | None = None,
    blocked_symbols: set[str] | None = None,
    ignored_symbols: set[str] | None = None,
    pre_rejected_symbols: list[dict[str, str]] | None = None,
    signal_dates: dict[str, str] | None = None,
    effective_investable_capital: float | None = None,
) -> dict[str, Any]:
    if net_liquidation_value is None:
        raise EngineInputError("net_liquidation_value_required")
    if effective_investable_capital is None:
        investable_capital = investable_capital_value(net_liquidation_value)
        liquidity_reserve = liquidity_reserve_value(net_liquidation_value)
    else:
        investable_capital = float(effective_investable_capital)
        liquidity_reserve = float(net_liquidation_value) - investable_capital
    blocked = _canonical_set(blocked_symbols)
    ignored = _canonical_set(ignored_symbols)
    active = _canonical_set(active_symbols)
    pending = _canonical_set(pending_buy_symbols)
    reserved_symbols = active | pending
    evaluations: list[EntryEvaluation] = []
    rejected: list[dict[str, str]] = list(pre_rejected_symbols or [])

    for symbol in sorted(closes_by_symbol):
        normalized_symbol = normalize_symbol(symbol)
        if normalized_symbol in blocked or normalized_symbol in ignored:
            rejected.append({"symbol": symbol, "reason": "manual_control_block"})
            continue
        if normalized_symbol in reserved_symbols:
            rejected.append({"symbol": symbol, "reason": "active_position_or_pending_buy"})
            continue
        try:
            evaluations.append(evaluate_entry_candidate(symbol, closes_by_symbol[symbol]))
        except ValueError as exc:
            reason = "insufficient_history" if "completed daily closes are required" in str(exc) else str(exc)
            rejected.append({"symbol": symbol, "reason": reason})

    if reserved_symbols:
        slots = available_slots(len(reserved_symbols), 0)
    else:
        slots = available_slots(open_positions, pending_buy_orders)
    selection = select_candidates(evaluations, slots)
    order_plans = []
    for item in selection.selected:
        plan = asdict(build_buy_order_plan(item, net_liquidation_value))
        if effective_investable_capital is not None:
            plan["allocation_value"] = investable_capital * APPROVED_PARAMETERS.position_allocation_pct
            plan["investable_capital"] = investable_capital
            plan["liquidity_reserve"] = liquidity_reserve
        order_plans.append(plan)
    for plan in order_plans:
        plan["side"] = "BUY"
        plan["order_type"] = "LIMIT"
        plan["signal_date"] = (signal_dates or {}).get(plan["symbol"], "")

    return {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "cycle_id": utc_timestamp(),
        "strategy_version": STRATEGY_VERSION,
        "net_liquidation_value": net_liquidation_value,
        "investable_capital": investable_capital,
        "liquidity_reserve": liquidity_reserve,
        "position_allocation_pct_of_investable_capital": APPROVED_PARAMETERS.position_allocation_pct,
        "open_positions": open_positions,
        "pending_buy_orders": pending_buy_orders,
        "reserved_position_slots": len(reserved_symbols) if reserved_symbols else open_positions + pending_buy_orders,
        "available_slots": slots,
        "ranking_applied": selection.ranking_applied,
        "evaluated_candidates": [_serialize_evaluation(item) for item in evaluations],
        "selected_candidates": [_serialize_evaluation(item) for item in selection.selected],
        "skipped_candidates": [_serialize_evaluation(item) for item in selection.skipped],
        "rejected_symbols": rejected,
        "order_plans": order_plans,
        "execute_orders": cfg.EXECUTE_ORDERS,
        "order_submission": "disabled" if not cfg.EXECUTE_ORDERS else "requires_broker_adapter",
    }


def evaluate_exit_signals(
    active_positions: dict[str, dict[str, Any]],
    closes_by_symbol: dict[str, list[float]] | None = None,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for symbol, position in sorted(active_positions.items()):
        previous_rsi = position.get("previous_rsi2")
        current_rsi = position.get("current_rsi2")
        if closes_by_symbol and symbol in closes_by_symbol:
            try:
                previous_rsi, current_rsi = latest_rsi_cross_values(closes_by_symbol[symbol])
            except ValueError:
                pass
        if previous_rsi is None or current_rsi is None:
            continue
        decision = exit_decision(
            float(previous_rsi),
            float(current_rsi),
            int(position.get("holding_trading_days", 0)),
        )
        if decision.should_exit:
            signals.append(
                {
                    "symbol": symbol,
                    "reason": decision.reason,
                    "timing": decision.timing,
                    "holding_trading_days": int(position.get("holding_trading_days", 0)),
                    "previous_rsi2": float(previous_rsi),
                    "current_rsi2": float(current_rsi),
                }
            )
    return signals


def build_sell_order_plans(exit_signals: list[dict[str, Any]], active_positions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    plans = []
    for signal in exit_signals:
        symbol = normalize_symbol(signal.get("symbol"))
        position = active_positions.get(symbol) or {}
        quantity = float(position.get("quantity", 0) or 0)
        if quantity <= 0:
            continue
        plans.append(
            {
                "symbol": symbol,
                "side": "SELL",
                "quantity": quantity,
                "order_type": "MARKET",
                "limit_price": None,
                "reason": signal.get("reason"),
                "timing": signal.get("timing"),
                "signal_date": signal.get("signal_date", ""),
            }
        )
    return plans



ORDER_TRANSMISSION_TZ = ZoneInfo(cfg.STRATEGY_CYCLE_TIMEZONE)


def wait_until_order_transmission_time() -> None:
    hour_text, minute_text = str(cfg.ORDER_TRANSMISSION_TIME_ET).split(":", 1)
    target_hour = int(hour_text)
    target_minute = int(minute_text)

    while True:
        if stop_bot_requested():
            raise RuntimeError("stop_requested_before_order_transmission")

        now_local = datetime.now(timezone.utc).astimezone(ORDER_TRANSMISSION_TZ)
        target = now_local.replace(
            hour=target_hour,
            minute=target_minute,
            second=0,
            microsecond=0,
        )

        if now_local >= target:
            return

        remaining = (target - now_local).total_seconds()
        time.sleep(min(1.0, max(0.05, remaining)))


def run_scan_once(*, net_liquidation_value: float | None = None, require_universe_file: bool = True) -> dict[str, Any]:
    cfg.ensure_runtime_dirs()
    cycle_started_at = utc_timestamp()
    write_runtime_health(
        strategy_engine_state=HEALTH_STARTING,
        message="scan starting",
        last_strategy_cycle_status="RUNNING",
        last_strategy_cycle_time_utc=cycle_started_at,
    )
    snapshot = ensure_runtime_ready(require_universe_file=require_universe_file)
    broker_context = collect_live_account_context(client_id=cfg.CLIENT_ID, readonly=not cfg.EXECUTE_ORDERS)
    live_values = broker_context["account_values"]
    if net_liquidation_value is None:
        net_liquidation_value = float(live_values["net_liquidation"])

    capital_control = evaluate_investable_capital_control(net_liquidation_value)

    effective_investable_capital = float(
        capital_control["effective_investable_capital"]
    )
    capital_budget = calculate_operational_buy_budget(
        live_values,
        strategy_cap=effective_investable_capital,
    )
    operational_buy_budget = float(capital_budget["operational_buy_budget"])

    if capital_control["compliance"] != "OK":
        log("investable capital compliance failure", level="ERROR", extra=capital_control)
    universe_config = load_universe_config()
    universe_path = _resolve_project_path(universe_config["source_path"])
    daily_bars_dir = _resolve_project_path(universe_config["daily_bars_dir"])
    universe_records = load_universe_symbol_records(universe_path, universe_config.get("symbol_column", "symbol"))
    symbols = list(universe_records["symbols"])
    market_data = load_daily_bar_data(symbols, daily_bars_dir)
    closes_by_symbol = market_data["closes_by_symbol"]
    data_exclusions = [
        {"symbol": row["symbol"], "reason": row["reason"]}
        for row in market_data["status_rows"]
        if row.get("status") == "excluded"
    ]
    refresh_status_path = cfg.STATE_DIR / "ibkr_market_data_refresh.json"
    try:
        current_refresh_status = json.loads(refresh_status_path.read_text(encoding="utf-8"))
    except Exception:
        current_refresh_status = {}
    acceptable_unresolved_symbols = {
        str(symbol)
        for symbol in (current_refresh_status.get("acceptable_unresolved_symbols") or [])
        if str(symbol)
    }
    market_data_read_errors = [
        row for row in data_exclusions
        if str(row.get("reason") or "").startswith("market_data_read_error:")
    ]
    if market_data_read_errors:
        sample = ",".join(str(row.get("symbol") or "") for row in market_data_read_errors[:10])
        raise EngineInputError(
            f"market_data_read_failures:{len(market_data_read_errors)};sample={sample}"
        )
    critical_market_data_exclusions = [
        row
        for row in data_exclusions
        if row.get("reason") in {"missing_market_data", "invalid_market_data_schema", "invalid_market_data_rows", "stale_market_data"}
        and str(row.get("symbol") or "") not in acceptable_unresolved_symbols
    ]
    state = rebuild_and_save(
        list(broker_context.get("positions") or []),
        list(broker_context.get("open_orders") or []),
    )
    scan = scan_from_closes(
        closes_by_symbol,
        net_liquidation_value=net_liquidation_value,
        open_positions=active_position_count(state),
        pending_buy_orders=pending_buy_count(state),
        active_symbols=active_position_symbols(state),
        pending_buy_symbols=pending_buy_symbols(state),
        blocked_symbols=read_blocked_symbols(),
        ignored_symbols=read_ignored_symbols(),
        pre_rejected_symbols=list(universe_records["exclusions"]) + data_exclusions,
        signal_dates=market_data["signal_dates"],
        effective_investable_capital=operational_buy_budget,
    )
    scan["universe_exclusions"] = list(universe_records["exclusions"])
    scan["configuration_sha256"] = snapshot["effective_configuration_sha256"]
    scan["configuration_files"] = {
        "strategy_constants": str(cfg.STRATEGY_CONSTANTS_FILE),
        "universe_config": str(cfg.UNIVERSE_CONFIG_FILE),
        "order_execution_config": str(cfg.ORDER_EXECUTION_CONFIG_FILE),
    }
    scan["strategy_parameters_loaded"] = asdict(APPROVED_PARAMETERS)
    capital_control = dict(capital_control)
    capital_control["account_equity_nlv"] = float(net_liquidation_value)
    capital_control.update(capital_budget)
    scan["investable_capital_control"] = capital_control
    refresh_status = current_refresh_status
    expected_market_data_date = str(
        refresh_status.get("expected_latest_completed_session")
        or expected_latest_completed_weekday()
    )
    latest_market_data_date = str(market_data.get("latest_date") or "")
    refresh_state = str(refresh_status.get("status") or "").upper()
    refresh_confirmed = refresh_state in {"OK", "DEGRADED_ACCEPTABLE"}
    market_data_date_current = latest_market_data_date == expected_market_data_date
    scan["market_data_compliance"] = {
        "compliance": "OK" if not critical_market_data_exclusions and market_data_date_current and refresh_confirmed else "INVALID",
        "critical_exclusion_count": len(critical_market_data_exclusions),
        "latest_date": latest_market_data_date,
        "expected_latest_completed_session": expected_market_data_date,
        "refresh_status": refresh_status.get("status", "MISSING"),
        "refresh_source": refresh_status.get("source", ""),
        "reason": (
            "ibkr_market_data_refresh_not_confirmed"
            if not refresh_confirmed
            else "market_data_latest_date_not_current"
            if not market_data_date_current
            else "market_data_not_current_or_invalid"
            if critical_market_data_exclusions
            else ""
        ),
    }
    scan["buy_submission_blocked"] = (
        capital_control["compliance"] != "OK"
        or scan["market_data_compliance"]["compliance"] != "OK"
    )
    scan["buy_submission_block_reason"] = capital_control["reason"] or scan["market_data_compliance"]["reason"]
    scan["universe_expected_symbols"] = len(symbols)
    scan["symbols_successfully_loaded"] = len(closes_by_symbol)
    scan["market_data_source"] = str(daily_bars_dir)
    scan["market_data_latest_date"] = market_data["latest_date"]
    scan["market_data_timestamp_utc"] = market_data["timestamp_utc"]
    scan["market_data_status"] = market_data["status_rows"]
    scan["signal_dates"] = market_data["signal_dates"]
    scan["live_account"] = {
        "timestamp_utc": broker_context["timestamp_utc"],
        "client_id": broker_context.get("client_id"),
        "account_mode": broker_context.get("account_mode"),
        "accounts": broker_context.get("accounts", []),
        "account_values": live_values,
    }
    scan["broker_positions"] = broker_context.get("positions", [])
    scan["broker_open_orders"] = broker_context.get("open_orders", [])
    scan["exit_signals"] = evaluate_exit_signals(state.get("active_positions") or {}, closes_by_symbol)
    for signal in scan["exit_signals"]:
        signal["signal_date"] = market_data["signal_dates"].get(signal["symbol"], "")
    scan["sell_order_plans"] = build_sell_order_plans(scan["exit_signals"], state.get("active_positions") or {})

    if cfg.EXECUTE_ORDERS:
        wait_until_order_transmission_time()
        broker_context = collect_live_account_context(
            client_id=cfg.CLIENT_ID,
            readonly=False,
        )
        fresh_values = broker_context["account_values"]
        scan["live_account"] = {
            "timestamp_utc": broker_context["timestamp_utc"],
            "client_id": broker_context.get("client_id"),
            "account_mode": broker_context.get("account_mode"),
            "accounts": broker_context.get("accounts", []),
            "account_values": fresh_values,
        }
        scan["broker_positions"] = broker_context.get("positions", [])
        scan["broker_open_orders"] = broker_context.get("open_orders", [])

    execution_report = process_order_plan(scan, broker_context, transmit=cfg.EXECUTE_ORDERS)
    scan["automated_execution"] = {
        "report_file": str(cfg.AUTOMATED_EXECUTION_REPORT_FILE),
        "transmission_permitted": execution_report["transmission_permitted"],
        "broker_orders_transmitted": execution_report["broker_orders_transmitted"],
        "intended_order_count": len(execution_report["intended_orders"]),
        "duplicate_preventions": execution_report["duplicate_preventions"],
        "rejected_orders": execution_report["rejected_orders"],
    }
    scan["order_submission"] = "submitted" if execution_report["broker_orders_transmitted"] else "disabled"
    order_plan_payload = {
        "timestamp_utc": scan["timestamp_utc"],
        "cycle_id": scan["cycle_id"],
        "order_plans": scan["order_plans"],
        "sell_order_plans": scan["sell_order_plans"],
    }
    atomic_write_json(cfg.ORDER_PLAN_FILE, order_plan_payload)
    try:
        broker_after = collect_live_account_context(client_id=cfg.RECONCILIATION_CLIENT_ID, readonly=True)
        reconciliation = reconcile_local_state(order_plan_payload, broker_after)
    except Exception as exc:
        write_runtime_health(
            strategy_engine_state=HEALTH_FAILED,
            order_engine_state=HEALTH_FAILED,
            startup_reconciliation_state=HEALTH_FAILED,
            trading_state="TRADING_BLOCKED",
            message="post-cycle reconciliation failed",
            last_strategy_cycle_status="FAILED",
            last_strategy_cycle_time_utc=scan["timestamp_utc"],
            extra={"error": repr(exc), "cycle_id": scan["cycle_id"]},
        )
        raise
    scan["reconciliation"] = {
        "report_file": str(cfg.RECONCILIATION_REPORT_FILE),
        "timestamp_utc": reconciliation.get("timestamp_utc"),
        "status": reconciliation.get("status"),
        "broker_position_count": reconciliation.get("broker_position_count"),
        "broker_open_order_count": reconciliation.get("broker_open_order_count"),
        "automated_order_updates": reconciliation.get("automated_order_updates"),
    }
    quality_report = record_quality_monitor_cycle(
        scan=scan,
        automated_execution_report=execution_report,
        broker_before=broker_context,
        broker_after=broker_after,
        reconciliation=reconciliation,
        scheduler_trigger_time_utc=cycle_started_at,
    )
    scan["quality_monitoring"] = quality_report or {"active": False}
    atomic_write_json(cfg.SCAN_REPORT_FILE, scan)
    record_daily_scan(scan)
    write_heartbeat(event="scan_once", selected=len(scan["selected_candidates"]))
    write_runtime_health(
        strategy_engine_state=HEALTH_OK,
        order_engine_state="DISABLED" if not cfg.EXECUTE_ORDERS else HEALTH_OK,
        startup_reconciliation_state=reconciliation.get("status", "RECONCILED"),
        trading_state=(
            "BUY_SUBMISSIONS_BLOCKED"
            if scan["buy_submission_blocked"]
            else "TRADING_ENABLED"
            if cfg.EXECUTE_ORDERS
            else "TRADING_DISABLED"
        ),
        message="scan completed",
        last_strategy_cycle_status="COMPLETED",
        last_strategy_cycle_time_utc=scan["timestamp_utc"],
        extra={
            "selected": len(scan["selected_candidates"]),
            "intended_orders": execution_report["intended_orders"],
            "broker_orders_transmitted": execution_report["broker_orders_transmitted"],
            "investable_capital_control": capital_control,
            "last_reconciliation": scan["reconciliation"],
            "quality_monitoring": scan["quality_monitoring"],
        },
    )
    log("scan completed", extra={"symbols": len(symbols), "selected": len(scan["selected_candidates"])})
    return scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TradingbotR1000 daily scan/order-plan engine")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--scan-once", action="store_true")
    parser.add_argument("--net-liquidation-value", "--capital", dest="net_liquidation_value", type=float)
    args = parser.parse_args(argv)

    try:
        if args.validate_only:
            snapshot = ensure_runtime_ready(require_universe_file=False)
            print(json.dumps(snapshot, indent=2, default=str))
            return 0
        if stop_bot_requested():
            write_runtime_health(strategy_engine_state=HEALTH_OK, message="stop requested before scan")
            return 0
        net_liquidation_value = args.net_liquidation_value
        scan = run_scan_once(net_liquidation_value=net_liquidation_value, require_universe_file=True)
        print(json.dumps({"selected": len(scan["selected_candidates"]), "orders": len(scan["order_plans"])}, indent=2))
        return 0
    except (AutomatedBrokerError, ConfigError, EngineInputError, LiveAccountError, OSError, ValueError) as exc:
        write_runtime_health(
            strategy_engine_state=HEALTH_FAILED,
            message=str(exc),
            last_strategy_cycle_status="FAILED",
            last_strategy_cycle_time_utc=utc_timestamp(),
        )
        log("engine failed", level="ERROR", extra={"error": str(exc)})
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
