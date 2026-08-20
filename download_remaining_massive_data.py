r"""Local launcher for resuming remaining Massive historical data downloads.

Run from C:\TradingbotR1000. If no mode is supplied, this defaults to
--download-missing, which downloads only symbols that are missing or not
trusted as complete by the current checkpoint/progress files.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.resume_massive_history import main  # noqa: E402


MODES = {"--validation-only", "--dry-run", "--download-missing"}


def default_to_download_missing(argv: list[str]) -> list[str]:
    if any(arg in MODES for arg in argv):
        return argv
    return ["--download-missing", *argv]


if __name__ == "__main__":
    raise SystemExit(main(default_to_download_missing(sys.argv[1:])))
