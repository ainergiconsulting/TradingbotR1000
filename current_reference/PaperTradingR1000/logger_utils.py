"""Logging helpers adapted from the Tradingbot2607 runtime pattern."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import threading
from pathlib import Path
from typing import Any, Iterator

import config as cfg
from monitoring_io import atomic_write_json


_LOG_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log(message: str, *, level: str = "INFO", extra: dict[str, Any] | None = None) -> None:
    cfg.ensure_runtime_dirs()
    row = {
        "timestamp": utc_now(),
        "level": level.upper(),
        "bot": cfg.BOT_NAME,
        "message": str(message),
    }
    if extra:
        row["extra"] = extra
    line = json.dumps(row, sort_keys=True)
    with _LOG_LOCK:
        cfg.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with cfg.LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


@contextmanager
def scheduler_log_context(name: str) -> Iterator[None]:
    log(f"{name}: started")
    try:
        yield
    except Exception as exc:
        log(f"{name}: failed: {exc!r}", level="ERROR")
        raise
    finally:
        log(f"{name}: finished")


def write_status_file(path: Path, payload: dict[str, Any]) -> None:
    payload = dict(payload)
    payload.setdefault("timestamp_utc", utc_now())
    payload.setdefault("bot", cfg.BOT_NAME)
    atomic_write_json(path, payload)
