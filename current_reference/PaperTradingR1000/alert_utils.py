"""Telegram/HTTP alert file helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config as cfg
from logger_utils import log
from monitoring_io import utc_timestamp


def write_alert(event: str, message: str, *, extra: dict[str, Any] | None = None) -> Path:
    cfg.ensure_runtime_dirs()
    cfg.ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "event": event,
        "message": message,
        "extra": extra or {},
    }
    target = cfg.ALERTS_DIR / f"{utc_timestamp().replace(':', '').replace('-', '')}_{event}.json"
    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    log("alert recorded", extra={"event": event})
    return target
