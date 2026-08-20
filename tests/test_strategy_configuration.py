import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import config_loader


class StrategyConfigurationTests(unittest.TestCase):
    def test_config_snapshot_matches_approved_strategy_constants(self):
        snapshot = config_loader.load_config_snapshot()

        self.assertEqual(snapshot["strategy_constants"]["universe"], "Russell 1000 stocks")
        self.assertEqual(snapshot["strategy_constants"]["strategy_version"], "1.1")
        self.assertEqual(snapshot["strategy_constants"]["investable_capital_pct"], 0.7)
        self.assertEqual(snapshot["strategy_constants"]["liquidity_reserve_pct"], 0.3)
        self.assertEqual(snapshot["strategy_constants"]["position_allocation_pct"], 0.2)
        self.assertFalse(snapshot["strategy_constants"]["leverage_allowed"])
        self.assertNotIn("order_type", snapshot["order_execution_config"])
        self.assertNotIn("time_in_force", snapshot["order_execution_config"])


if __name__ == "__main__":
    unittest.main()
