import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import config as cfg
import health_supervisor


class HealthSupervisorTests(unittest.TestCase):
    def setUp(self):
        self._cycle_watchdog_patcher = patch.object(
            health_supervisor, "strategy_cycle_watchdog",
            return_value={"status": "COMPLETED", "missed": False},
        )
        self._cycle_watchdog_patcher.start()
        self.addCleanup(self._cycle_watchdog_patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.old_status_file = cfg.SUPERVISOR_STATUS_FILE
        cfg.SUPERVISOR_STATUS_FILE = Path(self.tmp.name) / "health_supervisor_status.json"

    def tearDown(self):
        cfg.SUPERVISOR_STATUS_FILE = self.old_status_file
        self.tmp.cleanup()

    def _run(self, system_health, alerts):
        with patch.object(health_supervisor, "heartbeat_is_fresh", return_value=True), \
             patch.object(health_supervisor, "collect_system_health", return_value=system_health), \
             patch.object(health_supervisor, "write_alert", side_effect=lambda e, m: alerts.append((e, m))):
            return health_supervisor.evaluate_health()

    def test_persistent_timeout_becomes_degraded_and_alerts_once(self):
        connected = {
            "live_api_status": "CONNECTED", "gateway_process_status": "RUNNING",
            "api_socket_status": "CONNECTED", "live_api_error": ""
        }
        timeout = {
            "live_api_status": "DISCONNECTED", "gateway_process_status": "RUNNING",
            "api_socket_status": "CONNECTED", "live_api_error": "TimeoutError"
        }
        alerts = []
        self._run(connected, alerts)
        first = self._run(timeout, alerts)
        second = self._run(timeout, alerts)
        third = self._run(timeout, alerts)
        fourth = self._run(timeout, alerts)
        self.assertEqual(first["ibkr_connection_status"], "UNKNOWN")
        self.assertEqual(second["ibkr_connection_status"], "UNKNOWN")
        self.assertEqual(third["ibkr_connection_status"], "DEGRADED")
        self.assertEqual(third["status"], "DEGRADED_IBKR")
        self.assertEqual(fourth["ibkr_connection_status"], "DEGRADED")
        self.assertEqual([a[0] for a in alerts].count("ibkr_degraded"), 1)

    def test_connection_refused_is_disconnected_not_ok(self):
        alerts = []
        self._run({
            "live_api_status": "CONNECTED", "gateway_process_status": "RUNNING",
            "api_socket_status": "CONNECTED", "live_api_error": ""
        }, alerts)
        result = self._run({
            "live_api_status": "DISCONNECTED", "gateway_process_status": "RUNNING",
            "api_socket_status": "CONNECTION_REFUSED", "live_api_error": "CONNECTION_REFUSED"
        }, alerts)
        self.assertEqual(result["ibkr_connection_status"], "DISCONNECTED")
        self.assertEqual(result["status"], "IBKR_DISCONNECTED")
        self.assertEqual([a[0] for a in alerts].count("ibkr_disconnected"), 1)

    def test_recovery_from_degraded_alerts_once(self):
        alerts = []
        timeout = {
            "live_api_status": "DISCONNECTED", "gateway_process_status": "RUNNING",
            "api_socket_status": "CONNECTED", "live_api_error": "TimeoutError"
        }
        for _ in range(3):
            self._run(timeout, alerts)
        recovered = self._run({
            "live_api_status": "CONNECTED", "gateway_process_status": "RUNNING",
            "api_socket_status": "CONNECTED", "live_api_error": ""
        }, alerts)
        self.assertEqual(recovered["status"], "OK")
        self.assertEqual(recovered["consecutive_api_failures"], 0)
        self.assertEqual([a[0] for a in alerts].count("ibkr_reconnected"), 1)


if __name__ == "__main__":
    unittest.main()
