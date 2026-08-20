import sys
import tempfile
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import alert_utils
import config as cfg


class TelegramAlertsTests(unittest.TestCase):
    def test_alert_file_is_written_as_operational_evidence(self):
        old_alerts = cfg.ALERTS_DIR
        old_logs = cfg.LOGS_DIR
        old_log_file = cfg.LOG_FILE
        with tempfile.TemporaryDirectory() as tmp:
            cfg.ALERTS_DIR = Path(tmp) / "alerts"
            cfg.LOGS_DIR = Path(tmp) / "logs"
            cfg.LOG_FILE = cfg.LOGS_DIR / "bot_log.txt"
            try:
                path = alert_utils.write_alert("test", "message")
                self.assertTrue(path.exists())
            finally:
                cfg.ALERTS_DIR = old_alerts
                cfg.LOGS_DIR = old_logs
                cfg.LOG_FILE = old_log_file


if __name__ == "__main__":
    unittest.main()
