"""Runtime configuration for TradingbotR1000.

Strategy constants live in ``strategy.py`` and are mirrored in
``config_files/strategy_constants.json`` for auditability. Provider choices,
paths, client IDs, and safety switches are implementation settings, not trading
rules.
"""

from __future__ import annotations

import os
from pathlib import Path


BOT_NAME = "TradingbotR1000"
PACKAGE_NAME = "PaperTradingR1000"

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
CONFIG_DIR = BASE_DIR / "config_files"
STATE_DIR = BASE_DIR / "state"
LOGS_DIR = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports"
ALERTS_DIR = BASE_DIR / "Alerts"
PROJECT_CONFIG_DIR = PROJECT_ROOT / "config"

STATE_FILE = STATE_DIR / "bot_state.json"
LOG_FILE = LOGS_DIR / "bot_log.txt"
HEARTBEAT_FILE = STATE_DIR / "heartbeat.json"
BOT_STATUS_FILE = STATE_DIR / "bot_status.json"
RUNTIME_HEALTH_FILE = STATE_DIR / "runtime_health.json"
CONTROLLER_STATUS_FILE = STATE_DIR / "controller_status.json"
SUPERVISOR_STATUS_FILE = STATE_DIR / "health_supervisor_status.json"
CONTROL_CENTER_STATUS_FILE = STATE_DIR / "control_center_status.json"
BROKER_SNAPSHOT_FILE = STATE_DIR / "broker_snapshot.json"
AUTOMATED_ORDERS_FILE = STATE_DIR / "automated_orders.json"
AUTOMATED_EXECUTION_REPORT_FILE = REPORTS_DIR / "automated_execution_report.json"
SCHEDULER_STATE_FILE = STATE_DIR / "strategy_scheduler_state.json"
INVESTABLE_CAPITAL_CONTROL_FILE = STATE_DIR / "investable_capital_control.json"
QUALITY_MONITOR_STATE_FILE = STATE_DIR / "quality_monitoring_state.json"
DESIRED_STATE_FILE = STATE_DIR / "desired_running.json"
BOOT_AUTHORIZATION_FILE = STATE_DIR / "boot_authorization.json"
CONTROLLER_PID_FILE = STATE_DIR / "operational_controller.pid"
SUPERVISOR_PID_FILE = STATE_DIR / "health_supervisor.pid"
STOP_FILE = STATE_DIR / "stop_requested.txt"
STOP_ALL_FILE = STATE_DIR / "stop_all_orders.txt"
BLOCKED_SYMBOLS_FILE = STATE_DIR / "blocked_symbols.txt"
IGNORED_SYMBOLS_FILE = STATE_DIR / "ignored_symbols.txt"

STRATEGY_CONSTANTS_FILE = CONFIG_DIR / "strategy_constants.json"
UNIVERSE_CONFIG_FILE = CONFIG_DIR / "universe_config.json"
ORDER_EXECUTION_CONFIG_FILE = CONFIG_DIR / "order_execution_config.json"
TELEGRAM_CONFIG_FILE = BASE_DIR / "telegram_config.json"
TELEGRAM_CONFIG_EXAMPLE_FILE = BASE_DIR / "telegram_config.example.json"

SCAN_REPORT_FILE = REPORTS_DIR / "daily_scan_report.json"
ORDER_PLAN_FILE = REPORTS_DIR / "order_plan.json"
RECONCILIATION_REPORT_FILE = REPORTS_DIR / "reconciliation_report.json"
CONTROL_CENTER_EXPORT_FILE = REPORTS_DIR / "control_center_status_export.json"
QUALITY_MONITOR_REPORTS_DIR = REPORTS_DIR / "quality_monitoring"
EXECUTION_HISTORY_DB = REPORTS_DIR / "execution_history.sqlite3"
TRADE_LOG_FILE = REPORTS_DIR / "trade_log.csv"
TRADE_SPOOL_FILE = STATE_DIR / "trade_spool.jsonl"

HOST = os.environ.get("TRADINGBOTR1000_IBKR_HOST", "127.0.0.1")
PORT = int(os.environ.get("TRADINGBOTR1000_IBKR_PORT", "4002"))
CLIENT_ID = int(os.environ.get("TRADINGBOTR1000_IBKR_CLIENT_ID", "1000"))
MANUAL_CLIENT_ID = int(os.environ.get("TRADINGBOTR1000_MANUAL_CLIENT_ID", "1001"))
RECONCILIATION_CLIENT_ID = int(os.environ.get("TRADINGBOTR1000_RECONCILIATION_CLIENT_ID", "1002"))
REMOTE_CONTROL_CLIENT_ID = int(os.environ.get("TRADINGBOTR1000_REMOTE_CLIENT_ID", "1003"))
MARKET_DATA_CLIENT_ID = int(os.environ.get("TRADINGBOTR1000_MARKET_DATA_CLIENT_ID", "1005"))
TELEGRAM_CLIENT_ID = int(os.environ.get("TRADINGBOTR1000_TELEGRAM_CLIENT_ID", "1004"))

AUTOMATED_PAPER_EXECUTION_SWITCH = "TRADINGBOTR1000_ENABLE_AUTOMATED_PAPER_EXECUTION"
EXECUTE_ORDERS = os.environ.get(AUTOMATED_PAPER_EXECUTION_SWITCH, "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
PAPER_TRADING_REQUIRED = os.environ.get("TRADINGBOTR1000_PAPER_REQUIRED", "1").strip() not in {"0", "false", "FALSE", "no", "NO"}
CHECK_INTERVAL_SECONDS = int(os.environ.get("TRADINGBOTR1000_CHECK_INTERVAL_SECONDS", "60"))
STRATEGY_CYCLE_TIME_ET = os.environ.get("TRADINGBOTR1000_STRATEGY_CYCLE_TIME_ET", "09:28")
ORDER_TRANSMISSION_TIME_ET = os.environ.get("TRADINGBOTR1000_ORDER_TRANSMISSION_TIME_ET", "09:30")
STRATEGY_CYCLE_TIMEZONE = "America/New_York"
LIVE_ACCOUNT_MAX_AGE_SECONDS = int(os.environ.get("TRADINGBOTR1000_LIVE_ACCOUNT_MAX_AGE_SECONDS", "60"))
CAPITAL_SAFETY_MARGIN_PCT = float(os.environ.get("TRADINGBOTR1000_CAPITAL_SAFETY_MARGIN_PCT", "0.01"))
QUALITY_MONITOR_SESSION_LIMIT = int(os.environ.get("TRADINGBOTR1000_QUALITY_MONITOR_SESSION_LIMIT", "3"))
ALLOWED_CURRENCIES = tuple(
    item.strip().upper()
    for item in os.environ.get("TRADINGBOTR1000_ALLOWED_CURRENCIES", "USD").split(",")
    if item.strip()
)

REQUIRED_DIRECTORIES = (
    CONFIG_DIR,
    STATE_DIR,
    LOGS_DIR,
    REPORTS_DIR,
    QUALITY_MONITOR_REPORTS_DIR,
    ALERTS_DIR,
    PROJECT_CONFIG_DIR,
)


def ensure_runtime_dirs() -> None:
    for directory in REQUIRED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)


def project_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path)
