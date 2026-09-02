"""Read-only Telegram listener for TradingbotR1000."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from telegram_gateway_control import GatewayControlError, restart_gateway
from pathlib import Path
from typing import Any

import config as cfg
from telegram_commands import COMMANDS


POLL_TIMEOUT_SECONDS = 25
RETRY_SECONDS = 5


def _load_config() -> dict[str, Any]:
    path = getattr(cfg, "TELEGRAM_CONFIG_FILE", None)
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _token(config: dict[str, Any]) -> str:
    token_path = str(config.get("bot_token_file") or "").strip()
    if not token_path:
        raise RuntimeError("telegram token file not configured")

    path = Path(token_path)
    if not path.is_absolute():
        path = cfg.PROJECT_ROOT / path

    token = path.read_text(encoding="utf-8-sig").strip()
    if not token:
        raise RuntimeError("telegram token is empty")
    return token


def _api_call(token: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"

    if params:
        payload = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")
    else:
        request = urllib.request.Request(url)

    with urllib.request.urlopen(request, timeout=POLL_TIMEOUT_SECONDS + 10) as response:
        data = json.load(response)

    if not data.get("ok"):
        raise RuntimeError(f"telegram API call failed: {method}")

    return data


def _send_message(token: str, chat_id: int, text: str) -> None:
    _api_call(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text[:4000],
        },
    )


def _normalize_command(text: str) -> str:
    value = str(text or "").strip()
    if not value.startswith("/"):
        return ""
    command = value.split()[0][1:]
    command = command.split("@", 1)[0]
    return command.strip().lower()


def render_command(command: str) -> str:
    renderer = COMMANDS.get(command.strip().lower())
    if renderer is None:
        return "Unknown command."
    return renderer()


def main() -> int:
    config = _load_config()

    if not config.get("enabled"):
        print("Telegram listener disabled.")
        return 2

    allowed_chat_ids = {
        int(value)
        for value in config.get("allowed_chat_ids", [])
    }

    allowed_commands = {
        str(value).strip().lower()
        for value in config.get("commands", [])
        if str(value).strip()
    }

    token = _token(config)

    pending_gateway_restarts = {}
    gateway_restart_confirmation_seconds = 60

    offset = None
    consecutive_errors = 0
    max_consecutive_errors = 5

    # Discard updates that were already waiting before this listener started.
    # Only commands received after startup should be processed.
    try:
        pending = _api_call(
            token,
            "getUpdates",
            {
                "timeout": 0,
                "allowed_updates": json.dumps(["message"]),
            },
        )
        pending_updates = pending.get("result", [])
        if pending_updates:
            offset = max(int(item.get("update_id", 0)) for item in pending_updates) + 1
    except Exception as error:
        print(f"Telegram startup queue check failed: {type(error).__name__}")

    print("TradingbotR1000 Telegram listener started (read-only).")

    while True:
        try:
            params = {
                "timeout": POLL_TIMEOUT_SECONDS,
                "allowed_updates": json.dumps(["message"]),
            }
            if offset is not None:
                params["offset"] = offset

            response = _api_call(token, "getUpdates", params)
            consecutive_errors = 0

            for update in response.get("result", []):
                update_id = int(update.get("update_id", 0))
                offset = update_id + 1

                message = update.get("message") or {}
                chat = message.get("chat") or {}
                chat_id = chat.get("id")
                text = str(message.get("text") or "")

                if chat_id is None:
                    continue

                try:
                    chat_id_int = int(chat_id)
                except Exception:
                    continue

                if chat_id_int not in allowed_chat_ids:
                    continue

                command = _normalize_command(text)
                if not command:
                    continue

                if command not in allowed_commands:
                    _send_message(token, chat_id_int, "Command not allowed.")
                    continue

                if command == "gateway_restart":
                    pending_gateway_restarts[chat_id_int] = time.monotonic()
                    _send_message(
                        token,
                        chat_id_int,
                        "IB Gateway restart requested. "
                        "Confirm within 60 seconds with /confirm_gateway_restart",
                    )
                    continue

                if command == "confirm_gateway_restart":
                    requested_at = pending_gateway_restarts.pop(chat_id_int, None)

                    if requested_at is None:
                        _send_message(
                            token,
                            chat_id_int,
                            "No pending IB Gateway restart request.",
                        )
                        continue

                    if time.monotonic() - requested_at > gateway_restart_confirmation_seconds:
                        _send_message(
                            token,
                            chat_id_int,
                            "IB Gateway restart confirmation expired.",
                        )
                        continue

                    _send_message(
                        token,
                        chat_id_int,
                        "Restarting IB Gateway. Checking recovery...",
                    )

                    try:
                        result = restart_gateway(requested_by=chat_id_int)
                        if result.get("ok"):
                            reply = (
                                "IB Gateway restart completed.\n"
                                f"Service: {result.get('service')}\n"
                                f"API 4002: {result.get('api_4002')}"
                            )
                        else:
                            reply = (
                                "IB Gateway restarted but did not recover automatically.\n"
                                f"Service: {result.get('service')}\n"
                                f"API 4002: {result.get('api_4002')}\n"
                                "Manual IBKR authentication may be required."
                            )
                    except GatewayControlError as error:
                        reply = f"IB Gateway restart failed: {error}"

                    _send_message(token, chat_id_int, reply)
                    continue

                try:
                    reply = render_command(command)
                except Exception as error:
                    reply = f"{cfg.BOT_NAME}: command failed: {type(error).__name__}"

                _send_message(token, chat_id_int, reply)

        except KeyboardInterrupt:
            print("Telegram listener stopped.")
            return 0
        except Exception as error:
            consecutive_errors += 1
            print(
                f"Telegram listener error: {type(error).__name__} "
                f"({consecutive_errors}/{max_consecutive_errors})"
            )

            if consecutive_errors >= max_consecutive_errors:
                print(
                    "Telegram listener watchdog: too many consecutive errors; "
                    "exiting so systemd can restart the service."
                )
                return 1

            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
