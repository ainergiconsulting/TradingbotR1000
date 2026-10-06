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

    def test_reused_pid_for_unrelated_process_does_not_match_controller(self):
        with patch("runtime_processes.is_pid_running", return_value=True), patch(
            "runtime_processes.Path.read_bytes",
            return_value=b"python3\\x00telegram_listener.py\\x00",
        ):
            self.assertFalse(runtime_processes.pid_matches_command(851, "operational_controller.py"))

    def test_matching_controller_pid_is_recognized(self):
        with patch("runtime_processes.is_pid_running", return_value=True), patch(
            "runtime_processes.Path.read_bytes",
            return_value=b"python3\\x00operational_controller.py\\x00",
        ):
            self.assertTrue(runtime_processes.pid_matches_command(851, "operational_controller.py"))

    def test_controller_clears_reused_stale_pid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "controller.pid"
            pid_file.write_text("851", encoding="ascii")
            with patch.object(operational_controller.cfg, "CONTROLLER_PID_FILE", pid_file), patch.object(
                operational_controller, "pid_matches_command", return_value=False
            ):
                self.assertFalse(operational_controller.another_controller_running())
            self.assertFalse(pid_file.exists())

    def test_market_data_refresh_keeps_controller_heartbeat_alive(self):
        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(*args, **kwargs):
            time.sleep(0.05)
            return Completed()

        with patch.object(operational_controller.subprocess, "run", side_effect=fake_run), patch.object(
            operational_controller, "write_heartbeat"
        ) as heartbeat:
            self.assertEqual(operational_controller._run_market_data_refresh_once(), 0)

        events = [call.kwargs.get("event") for call in heartbeat.call_args_list]
        self.assertIn("market_data_refresh", events)
        self.assertIn("market_data_refresh_complete", events)


class WeeklyMaintenanceHardeningTests(unittest.TestCase):
    def test_health_supervisor_validates_pid_command_before_duplicate_exit(self):
        root = Path(__file__).resolve().parents[1]
        source = (
            root / "current_reference" / "PaperTradingR1000" / "health_supervisor.py"
        ).read_text(encoding="utf-8")
        self.assertIn('pid_matches_command(status["pid"], "health_supervisor.py")', source)
        self.assertIn('clear_pid(cfg.SUPERVISOR_PID_FILE, status["pid"])', source)

    def test_deployed_systemd_units_prevent_restart_storm_on_duplicate_exit(self):
        root = Path(__file__).resolve().parents[1]
        controller = (
            root / "deploy" / "systemd" / "tradingbot-controller.service"
        ).read_text(encoding="utf-8")
        supervisor = (
            root / "deploy" / "systemd" / "tradingbot-supervisor.service"
        ).read_text(encoding="utf-8")
        for unit in (controller, supervisor):
            self.assertIn("RestartPreventExitStatus=10", unit)
            self.assertIn("StartLimitIntervalSec=300", unit)
            self.assertIn("StartLimitBurst=5", unit)

    def test_weekly_maintenance_stops_both_pid_owners_and_removes_pid_files(self):
        root = Path(__file__).resolve().parents[1]
        script = (
            root / "deploy" / "maintenance" / "weekly_maintenance.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "systemctl stop tradingbot-controller.service tradingbot-health-supervisor.service",
            script,
        )
        self.assertIn("operational_controller.pid", script)
        self.assertIn("health_supervisor.pid", script)
        self.assertIn("NEEDRESTART_MODE=l", script)
        self.assertIn("systemctl reboot", script)


if __name__ == "__main__":
    unittest.main()
