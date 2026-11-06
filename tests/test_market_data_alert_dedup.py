import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import telegram_alerts


class MarketDataAlertDedupTests(unittest.TestCase):
    def test_same_expected_session_is_not_notified_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            alerts_dir = Path(tmp)
            existing = alerts_dir / "20261105T214544Z_market_data_refresh_failure.json"
            existing.write_text(
                json.dumps({
                    "event": "market_data_refresh_failure",
                    "message": "Detail: attempts=3; exit_code=2; failure_count=3; expected_session=20261105",
                }),
                encoding="utf-8",
            )
            with patch.object(telegram_alerts.cfg, "ALERTS_DIR", alerts_dir), \
                 patch.object(telegram_alerts, "write_alert") as mocked:
                telegram_alerts.alert_market_data_refresh_failure(
                    "attempts=3; exit_code=2; failure_count=3; expected_session=20261105"
                )
            mocked.assert_not_called()

    def test_new_expected_session_is_notified(self):
        with tempfile.TemporaryDirectory() as tmp:
            alerts_dir = Path(tmp)
            existing = alerts_dir / "20261105T214544Z_market_data_refresh_failure.json"
            existing.write_text(
                json.dumps({
                    "event": "market_data_refresh_failure",
                    "message": "Detail: attempts=3; exit_code=2; failure_count=3; expected_session=20261105",
                }),
                encoding="utf-8",
            )
            with patch.object(telegram_alerts.cfg, "ALERTS_DIR", alerts_dir), \
                 patch.object(telegram_alerts, "write_alert") as mocked:
                telegram_alerts.alert_market_data_refresh_failure(
                    "attempts=3; exit_code=2; failure_count=2; expected_session=20261106"
                )
            mocked.assert_called_once()
            self.assertEqual(mocked.call_args.args[0], "market_data_refresh_failure")


if __name__ == "__main__":
    unittest.main()
