import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import config as cfg
import manual_control_console


class ManualConsoleMigrationTests(unittest.TestCase):
    def test_uses_r1000_watchlist_path_for_buy_options(self):
        self.assertEqual(manual_control_console.PROJECT_DIR, cfg.PROJECT_ROOT)
        self.assertEqual(
            manual_control_console.MANUAL_WATCHLIST_XLSX,
            cfg.PROJECT_ROOT / "config" / "manual_trading_watchlist.xlsx",
        )
        self.assertTrue(manual_control_console.MANUAL_WATCHLIST_XLSX.exists())
        self.assertEqual(manual_control_console.MENU_OPTIONS["4"], "BUY Limit")
        self.assertEqual(manual_control_console.MENU_OPTIONS["6"], "BUY Market")

    def test_option_13_is_investable_capital_control(self):
        self.assertEqual(manual_control_console.MENU_OPTIONS["13"], "Investable Capital Control")

    def test_stop_file_targets_r1000_runtime_state(self):
        self.assertEqual(manual_control_console.STOP_BOT_FILE, cfg.STOP_FILE)


if __name__ == "__main__":
    unittest.main()
