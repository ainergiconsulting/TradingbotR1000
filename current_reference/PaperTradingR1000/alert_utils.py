"""Telegram/HTTP alert file helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import urllib.parse
import urllib.request

import config as cfg
from logger_utils import log
from monitoring_io import utc_timestamp


def _load_telegram_config() -> dict[str, Any]:
    path = getattr(cfg, "TELEGRAM_CONFIG_FILE", None)
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_token_file(config: dict[str, Any]) -> Path | None:
    token_path = str(config.get("bot_token_file") or "").strip()
    if not token_path:
        return None

    path = Path(token_path)
    if not path.is_absolute():
        path = cfg.PROJECT_ROOT / path
    return path


def send_telegram_message(message: str) -> bool:
    config = _load_telegram_config()

    if not config.get("enabled"):
        return False

    chat_ids = config.get("allowed_chat_ids")
    if not isinstance(chat_ids, list) or not chat_ids:
        log("telegram alert skipped", level="WARNING", extra={"reason": "no_allowed_chat_ids"})
        return False

    token_file = _resolve_token_file(config)
    if token_file is None:
        log("telegram alert skipped", level="WARNING", extra={"reason": "token_file_not_configured"})
        return False

    try:
        token = token_file.read_text(encoding="utf-8-sig").strip()
    except Exception as error:
        log(
            "telegram alert failed",
            level="WARNING",
            extra={"reason": "token_file_unavailable", "error_type": type(error).__name__},
        )
        return False

    if not token:
        log("telegram alert failed", level="WARNING", extra={"reason": "empty_token"})
        return False

    sent_any = False

    for chat_id in chat_ids:
        try:
            payload = urllib.parse.urlencode(
                {
                    "chat_id": chat_id,
                    "text": message,
                }
            ).encode("utf-8")

            request = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                method="POST",
            )

            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.load(response)

            if result.get("ok"):
                sent_any = True
            else:
                log(
                    "telegram alert failed",
                    level="WARNING",
                    extra={"reason": "telegram_api_not_ok", "chat_id": str(chat_id)},
                )

        except Exception as error:
            log(
                "telegram alert failed",
                level="WARNING",
                extra={
                    "reason": "send_exception",
                    "chat_id": str(chat_id),
                    "error_type": type(error).__name__,
                },
            )

    return sent_any


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

    telegram_message = (
        f"{cfg.BOT_NAME}\n"
        f"Event: {event}\n"
        f"{message}"
    )
    send_telegram_message(telegram_message)

    return target
