"""Read-only configuration validation entry point.

TradingbotR1000 strategy constants are not edited here; this tool validates the
runtime configuration and prints the effective hash for operator evidence.
"""

from __future__ import annotations

import json

from config_loader import load_config_snapshot


def main() -> int:
    print(json.dumps(load_config_snapshot(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
