"""Standalone Flex analytics configuration for TradingbotR1000."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / "current_reference" / "PaperTradingR1000"
ANALYTICS_DIR = PROJECT_ROOT / "analytics"
RAW_DIR = ANALYTICS_DIR / "data" / "raw"
NORMALIZED_DIR = ANALYTICS_DIR / "data" / "normalized"
EXCEL_FEED_DIR = ANALYTICS_DIR / "data" / "excel_feed"
DATABASE_DIR = ANALYTICS_DIR / "database"
REPORTS_DIR = ANALYTICS_DIR / "reports"
LOGS_DIR = ANALYTICS_DIR / "logs"
DEFAULT_DB_PATH = DATABASE_DIR / "flex_analytics.sqlite3"
DEFAULT_REPORT_PATH = REPORTS_DIR / "TradingbotR1000_Performance.xlsx"
DEFAULT_CONFIG_PATH = RUNTIME_DIR / "flex_config.json"
DEFAULT_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
try:
    NEW_YORK_TZ = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:  # Windows hosts may not have tzdata installed.
    NEW_YORK_TZ = timezone(timedelta(hours=-5), name="America/New_York")


@dataclass(frozen=True)
class FlexAnalyticsConfig:
    enabled: bool
    token: str
    daily_activity_query_id: str
    base_url: str = DEFAULT_BASE_URL
    output_dir: Path = RAW_DIR
    wait_seconds: int = 20
    max_get_attempts: int = 5
    retry_seconds: int = 10


def ensure_analytics_dirs() -> None:
    for directory in (RAW_DIR, NORMALIZED_DIR, EXCEL_FEED_DIR, DATABASE_DIR, REPORTS_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def load_config(path: Path | None = None) -> FlexAnalyticsConfig:
    config_path = Path(path or os.environ.get("IBKR_FLEX_ANALYTICS_CONFIG", "") or DEFAULT_CONFIG_PATH)
    if not config_path.exists():
        raise FileNotFoundError(f"missing Flex analytics config:{config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return FlexAnalyticsConfig(
        enabled=bool(data.get("enabled", False)),
        token=os.environ.get("IBKR_FLEX_TOKEN") or str(data.get("token", "")).strip(),
        daily_activity_query_id=os.environ.get("IBKR_FLEX_DAILY_ACTIVITY_QUERY_ID")
        or str(data.get("daily_activity_query_id", "")).strip(),
        base_url=str(data.get("base_url", DEFAULT_BASE_URL)).strip() or DEFAULT_BASE_URL,
        output_dir=Path(data.get("output_dir") or RAW_DIR),
        wait_seconds=int(data.get("wait_seconds", 20)),
        max_get_attempts=int(data.get("max_get_attempts", 5)),
        retry_seconds=int(data.get("retry_seconds", 10)),
    )


def validate_config(config: FlexAnalyticsConfig) -> None:
    if not config.enabled:
        raise ValueError("Flex analytics is disabled")
    if not config.token:
        raise ValueError("Flex token is required")
    if not config.daily_activity_query_id:
        raise ValueError("daily activity query id is required")
