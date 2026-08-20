"""Monitoring state helpers for TradingbotR1000."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import config as cfg
from logger_utils import log
from monitoring_io import atomic_write_json, utc_timestamp


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def write_bot_status(status: str, *, detail: str = "", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    timestamp = utc_timestamp()
    payload = {
        "bot": cfg.BOT_NAME,
        "timestamp": timestamp,
        "timestamp_utc": timestamp,
        "status": status,
        "detail": detail,
    }
    if extra:
        payload["extra"] = extra
    atomic_write_json(cfg.BOT_STATUS_FILE, payload)
    return payload


def check_disk_space(path: Path = cfg.PROJECT_ROOT, minimum_free_mb: int = 512) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    free_mb = int(usage.free / (1024 * 1024))
    result = {"path": str(path), "free_mb": free_mb, "ok": free_mb >= minimum_free_mb}
    if not result["ok"]:
        log("low disk space", level="WARNING", extra=result)
    return result


def collect_runtime_status() -> dict[str, Any]:
    return {
        "bot_status": read_json(cfg.BOT_STATUS_FILE),
        "runtime_health": read_json(cfg.RUNTIME_HEALTH_FILE),
        "heartbeat": read_json(cfg.HEARTBEAT_FILE),
        "controller": read_json(cfg.CONTROLLER_STATUS_FILE),
        "supervisor": read_json(cfg.SUPERVISOR_STATUS_FILE),
        "scan_report": read_json(cfg.SCAN_REPORT_FILE),
        "disk": check_disk_space(),
    }
