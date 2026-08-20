from __future__ import annotations

import subprocess
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
subprocess.Popen(["cmd", "/c", str(project_root / "run" / "start_trading_system.bat")], cwd=str(project_root))
