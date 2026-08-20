"""Operational alert rendering for TradingbotR1000."""

from __future__ import annotations

from typing import Any

from alert_utils import write_alert


def alert_scan_completed(selected_count: int, order_count: int) -> None:
    write_alert(
        "scan_completed",
        f"R1000 scan completed: {selected_count} selected, {order_count} order plans.",
    )


def alert_engine_failure(error: str, *, extra: dict[str, Any] | None = None) -> None:
    write_alert("engine_failure", error, extra=extra)


def start_alert_thread(*_args: Any, **_kwargs: Any) -> None:
    return None
