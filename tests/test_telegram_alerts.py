import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import alert_utils
import config as cfg
import telegram_alerts


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


class TelegramPreviewAlertsTests(unittest.TestCase):
    def test_preopen_preview_alert_discloses_order_details_without_submission(self):
        scan = {
            "preview_trade_date_et": "2026-09-21",
            "market_data_latest_date": "20260918",
            "selected_candidates": [{"symbol": "AAA"}],
            "order_plans": [{
                "symbol": "AAA",
                "side": "BUY",
                "order_type": "LIMIT",
                "allocation_value": 9700.0,
                "limit_price": 97.0,
            }],
            "sell_order_plans": [],
        }
        with patch.object(telegram_alerts, "write_alert") as write:
            telegram_alerts.alert_preopen_preview(scan)

        write.assert_called_once()
        event, message = write.call_args.args[:2]
        self.assertEqual(event, "preopen_preview")
        self.assertIn("R1000 PRE-OPEN PLAN READY.", message)
        self.assertIn("Selected candidates: 1", message)
        self.assertIn("Broker submitted: 0", message)
        self.assertIn("BUY AAA | planned qty 100 | LIMIT @ $97.00", message)
        self.assertIn("no broker order has been sent", message.lower())
