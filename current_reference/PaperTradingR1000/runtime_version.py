"""Runtime version and configuration hash evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import config as cfg
from config_loader import load_config_snapshot
from monitoring_io import atomic_write_json, utc_timestamp
from strategy import STRATEGY_SPECIFICATION, STRATEGY_VERSION


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_runtime_version() -> dict[str, Any]:
    strategy_path = cfg.BASE_DIR / "strategy.py"
    config_snapshot = load_config_snapshot()
    payload = {
        "bot": cfg.BOT_NAME,
        "timestamp_utc": utc_timestamp(),
        "strategy_version": STRATEGY_VERSION,
        "strategy_specification": STRATEGY_SPECIFICATION,
        "strategy_module_sha256": sha256_file(strategy_path),
        "effective_configuration_sha256": config_snapshot["effective_configuration_sha256"],
        "configuration": config_snapshot,
    }
    payload["overall_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return payload


def write_runtime_version(path: Path = cfg.STATE_DIR / "runtime_version.json") -> dict[str, Any]:
    payload = build_runtime_version()
    atomic_write_json(path, payload)
    return payload
