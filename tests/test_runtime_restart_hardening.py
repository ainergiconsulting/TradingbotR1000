import sys
import unittest
from pathlib import Path
import tempfile
import time


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import operational_controller
import heartbeat_utils
import runtime_processes
from unittest.mock import patch


class RuntimeRestartHardeningTests(unittest.TestCase):
    def test_controller_requires_boot_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            desired = Path(directory) / "desired_running.json"
            authorization = Path(directory) / "boot_authorization.json"
            with patch.object(operational_controller.cfg, "DESIRED_STATE_FILE", desired), patch.object(
                operational_controller.cfg, "BOOT_AUTHORIZATION_FILE", authorization
            ):
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

    def test_cross_user_permission_error_still_means_process_exists(self):
        with patch("runtime_processes.os.kill", side_effect=PermissionError):
            self.assertTrue(runtime_processes.is_pid_running(12345))

    def test_missing_process_is_not_running(self):
        with patch("runtime_processes.os.kill", side_effect=ProcessLookupError):
            self.assertFalse(runtime_processes.is_pid_running(12345))


if __name__ == "__main__":
    unittest.main()
