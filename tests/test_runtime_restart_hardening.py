import sys
import unittest
from pathlib import Path
import tempfile
import time


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import operational_controller
import heartbeat_utils


class RuntimeRestartHardeningTests(unittest.TestCase):
    def test_controller_requires_boot_authorization(self):
        self.assertIsInstance(operational_controller.write_desired_running(False), dict)
        self.assertIsInstance(operational_controller.authorize_current_boot(), dict)
        self.assertTrue(operational_controller.is_authorized())

    def test_stale_heartbeat_fails_freshness_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "heartbeat.json"
            path.write_text("{}", encoding="utf-8")
            old = time.time() - 3600
            path.touch()
            import os

            os.utime(path, (old, old))

            self.assertFalse(heartbeat_utils.heartbeat_is_fresh(path, max_age_seconds=60))


if __name__ == "__main__":
    unittest.main()
