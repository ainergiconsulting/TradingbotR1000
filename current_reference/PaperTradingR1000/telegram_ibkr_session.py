"""Read-only IBKR session helper for Telegram commands."""

from __future__ import annotations

from typing import Any

import config as cfg
from ibkr_utils import connect


_SESSION: Any | None = None


def get_telegram_ibkr_session() -> Any:
    global _SESSION
    if _SESSION is None:
        _SESSION = connect(client_id=cfg.TELEGRAM_CLIENT_ID, readonly=True)
    return _SESSION


def close_telegram_ibkr_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.disconnect()
        _SESSION = None
