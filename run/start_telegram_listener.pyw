from __future__ import annotations

import subprocess
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
bot_dir = project_root / "current_reference" / "PaperTradingR1000"
subprocess.Popen(["python", "telegram_listener.py", "status"], cwd=str(bot_dir))
