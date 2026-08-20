"""Heartbeat utilities for controller and health-supervisor visibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import config as cfg
from logger_utils import log
from monitoring_io import atomic_write_json, utc_timestamp


def write_heartbeat(path: Path = cfg.HEARTBEAT_FILE, **extra: Any) -> dict[str, Any]:
    payload = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "status": "alive",
    }
    payload.update(extra)
    atomic_write_json(path, payload)
    return payload


def heartbeat_is_fresh(path: Path = cfg.HEARTBEAT_FILE, max_age_seconds: int = 180) -> bool:
    if not path.exists():
        return False
    age = __import__("time").time() - path.stat().st_mtime
    return age <= max_age_seconds


def write_startup_heartbeat() -> None:
    write_heartbeat(event="startup")
    log("startup heartbeat written")
