"""Minimal read-only Telegram listener entry point.

The runtime keeps Telegram monitoring decoupled from trading decisions. This
module validates command rendering without requiring a network listener during
migration.
"""

from __future__ import annotations

import argparse

from telegram_commands import COMMANDS


def render_command(command: str) -> str:
    renderer = COMMANDS.get(command.strip().lower())
    if renderer is None:
        return "Unknown command."
    return renderer()


def main() -> int:
    parser = argparse.ArgumentParser(description="TradingbotR1000 Telegram command renderer")
    parser.add_argument("command", nargs="?", default="status")
    args = parser.parse_args()
    print(render_command(args.command))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
