#!/usr/bin/env python3
"""Legacy compatibility entry point.

This filename is retained so old references fail clearly instead of importing
obsolete probe assumptions as if they were strategy behavior.
"""

from __future__ import annotations

from test_ibkr_r1000 import main


if __name__ == "__main__":
    raise SystemExit(main())
