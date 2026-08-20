import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import telegram_commands


class TelegramMonitoringTests(unittest.TestCase):
    def test_status_renderer_is_read_only(self):
        text = telegram_commands.render_status()

        self.assertIn("TradingbotR1000 status", text)


if __name__ == "__main__":
    unittest.main()
