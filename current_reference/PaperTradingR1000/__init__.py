"""TradingbotR1000 paper-trading reference package.

Tradingbot2607 used a flat module layout executed from the runtime directory.
The R1000 package keeps that operational shape for launcher compatibility while
also allowing package-style imports in tests.
"""

from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))


__all__ = ["PACKAGE_DIR"]
