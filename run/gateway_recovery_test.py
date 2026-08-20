from __future__ import annotations

import sys
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

from gateway_status import main


if __name__ == "__main__":
    raise SystemExit(main())
