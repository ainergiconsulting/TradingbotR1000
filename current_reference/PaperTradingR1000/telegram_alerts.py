"""Operational alert rendering for TradingbotR1000."""

from __future__ import annotations

from typing import Any
import time

import config as cfg
from alert_utils import write_alert


def alert_scan_completed(
    selected_count: int,
    planned_count: int,
    rejected_or_skipped_count: int,
    broker_submitted_count: int,
    effective_investable_capital: float,
) -> None:
    write_alert(
        "scan_completed",
        (
            "R1000 scan completed.\n"
            f"Selected candidates: {selected_count}\n"
            f"Planned orders: {planned_count}\n"
            f"Rejected/skipped: {rejected_or_skipped_count}\n"
            f"Broker submitted: {broker_submitted_count}\n"
            f"Operational buy budget: ${effective_investable_capital:,.2f}"
        ),
    )


def alert_engine_failure(error: str, *, extra: dict[str, Any] | None = None) -> None:
    # Persistent anti-spam guard: repeated controller retries or systemd
    # restarts must not generate a Telegram storm for the same continuing
    # incident. Health-supervisor transition alerts still report IBKR
    # disconnect/reconnect events independently.
    try:
        recent = max(cfg.ALERTS_DIR.glob("*_engine_failure.json"), key=lambda p: p.stat().st_mtime)
        if time.time() - recent.stat().st_mtime < 6 * 60 * 60:
            return
    except (ValueError, FileNotFoundError, OSError):
        pass
    write_alert("engine_failure", error, extra=extra)


def start_alert_thread(*_args: Any, **_kwargs: Any) -> None:
    return None


def alert_market_data_refresh_failure(detail: str) -> None:
    write_alert(
        "market_data_refresh_failure",
        (
            "R1000 MARKET DATA ALERT.\n"
            "IBKR daily-bar refresh failed.\n"
            "Automated BUY orders will remain fail-closed until current data is confirmed.\n"
            f"Detail: {detail}"
        ),
    )


def alert_market_data_refresh_warning(detail: str) -> None:
    write_alert(
        "market_data_refresh_warning",
        "IBKR market-data refresh completed with a small unresolved symbol set. "
        "Trading may proceed using the validated universe subset. " + detail,
    )


def alert_universe_refresh_failure(detail: str) -> None:
    write_alert(
        "universe_refresh_failure",
        "Weekly IWB/Russell 1000 universe refresh failed. Trading will continue with the last validated universe. " + detail,
    )
