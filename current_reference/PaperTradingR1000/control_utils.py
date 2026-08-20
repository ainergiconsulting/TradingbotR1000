"""Runtime control-file utilities."""

from __future__ import annotations

from pathlib import Path

import config as cfg
from logger_utils import log
try:
    from .symbol_mapping import canonical_symbol
except ImportError:  # pragma: no cover - supports direct script execution.
    from symbol_mapping import canonical_symbol


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def request_stop(reason: str = "operator_request") -> None:
    _touch(cfg.STOP_FILE, reason)
    log("stop requested", extra={"reason": reason})


def clear_stop_request() -> None:
    if cfg.STOP_FILE.exists():
        cfg.STOP_FILE.unlink()
        log("stop request cleared")


def stop_bot_requested() -> bool:
    return cfg.STOP_FILE.exists()


def stop_all_active() -> bool:
    return cfg.STOP_ALL_FILE.exists()


def read_symbol_file(path: Path) -> set[str]:
    if not path.exists():
        return set()
    symbols = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        symbol = canonical_symbol(text)
        if symbol:
            symbols.add(symbol)
    return symbols


def read_blocked_symbols() -> set[str]:
    return read_symbol_file(cfg.BLOCKED_SYMBOLS_FILE)


def read_ignored_symbols() -> set[str]:
    return read_symbol_file(cfg.IGNORED_SYMBOLS_FILE)
