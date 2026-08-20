#!/usr/bin/env python3
"""Legacy compatibility entry point.

The previous file was a provider-specific historical-data probe, not the
approved TradingbotR1000 strategy implementation.

Use the strategy tests in tests/test_strategy_core.py for the current
specification-aligned implementation.
"""

from __future__ import annotations


def main() -> int:
    print(
        "This legacy IBKR data probe is not part of the approved "
        "TradingbotR1000 strategy implementation. Run "
        "`python -m unittest discover -s tests` for current strategy checks."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
