import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import telegram_commands


class TelegramMonitoringTests(unittest.TestCase):
    def test_status_renderer_is_read_only(self):
        text = telegram_commands.render_status()
        self.assertIn("TradingbotR1000 status", text)

    def test_render_portfolio_shows_pending_order_details(self):
        snapshot = {
            "account_mode": "PAPER",
            "timestamp_utc": "2026-09-03T13:43:11Z",
            "account_values": {
                "net_liquidation": 1000000.0,
                "cash": 1000000.0,
                "available_funds": 1000000.0,
                "lookahead_available_funds": 1000000.0,
                "buying_power": 4000000.0,
            },
            "positions": [],
            "open_orders": [
                {"symbol": "FAST", "action": "BUY", "quantity": "4272", "limit_price": "46.49", "status": "Submitted", "filled": "0", "remaining": "4272"},
                {"symbol": "SNOW", "action": "BUY", "quantity": "669", "limit_price": "296.66", "status": "Submitted", "filled": "100", "remaining": "569"},
            ],
        }
        with patch.object(telegram_commands, "collect_live_account_context", return_value=snapshot):
            with patch.object(telegram_commands, "evaluate", return_value={"effective_investable_capital": 1000000.0}):
                text = telegram_commands.render_portfolio()
        self.assertIn("Pending orders: 2", text)
        self.assertIn("FAST BUY", text)
        self.assertIn("Ordered: 4272 @ $46.49", text)
        self.assertIn("Filled: 0", text)
        self.assertIn("Pending: 4272", text)
        self.assertIn("SNOW BUY", text)
        self.assertIn("Filled: 100", text)
        self.assertIn("Pending: 569", text)


if __name__ == "__main__":
    unittest.main()
