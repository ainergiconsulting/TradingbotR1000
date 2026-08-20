"""Build the offline TradingbotR1000 Security Master."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from r1000_data_integrity.security_master import (  # noqa: E402
    build_parser,
    build_security_master,
    paths_from_args,
    validate_security_master,
)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = paths_from_args(args)
    if not args.validate_only:
        result = build_security_master(paths)
        print(
            json.dumps(
                {
                    "stage": "security_master_build",
                    "database": str(result.database),
                    "securities": result.securities,
                    "tradable": result.tradable,
                    "excluded": result.excluded,
                    "blocked": result.blocked,
                    "review_required": result.review_required,
                },
                indent=2,
            )
        )
    validation = validate_security_master(paths)
    print(json.dumps({"stage": "security_master_validation", "ok": validation["ok"], "summary": validation["summary"]}, indent=2))
    return 0 if validation["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
