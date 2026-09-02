import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

from live_account import LiveAccountError, calculate_operational_buy_budget


class OperationalCapitalBudgetTests(unittest.TestCase):
    def test_uses_available_funds_with_one_percent_margin(self):
        result = calculate_operational_buy_budget(
            {"available_funds": 100_000.0, "lookahead_available_funds": 100_000.0},
            strategy_cap=100_000.0,
            safety_margin_pct=0.01,
        )
        self.assertEqual(result["broker_available_capital"], 100_000.0)
        self.assertEqual(result["capital_safety_margin_value"], 1_000.0)
        self.assertEqual(result["operational_buy_budget"], 99_000.0)

    def test_lookahead_available_funds_can_only_reduce_budget(self):
        result = calculate_operational_buy_budget(
            {"available_funds": 100_000.0, "lookahead_available_funds": 90_000.0},
            strategy_cap=100_000.0,
            safety_margin_pct=0.01,
        )
        self.assertEqual(result["broker_available_capital"], 90_000.0)
        self.assertEqual(result["operational_buy_budget"], 89_100.0)

    def test_strategy_cap_can_reduce_but_not_increase_broker_capital(self):
        lower = calculate_operational_buy_budget(
            {"available_funds": 100_000.0}, strategy_cap=80_000.0, safety_margin_pct=0.01
        )
        higher = calculate_operational_buy_budget(
            {"available_funds": 100_000.0}, strategy_cap=500_000.0, safety_margin_pct=0.01
        )
        self.assertEqual(lower["operational_buy_budget"], 79_200.0)
        self.assertEqual(higher["operational_buy_budget"], 99_000.0)

    def test_nlv_and_buying_power_do_not_increase_budget(self):
        result = calculate_operational_buy_budget(
            {
                "available_funds": 100_000.0,
                "lookahead_available_funds": 100_000.0,
                "net_liquidation": 1_000_000.0,
                "buying_power": 4_000_000.0,
            },
            strategy_cap=1_000_000.0,
            safety_margin_pct=0.01,
        )
        self.assertEqual(result["operational_buy_budget"], 99_000.0)

    def test_invalid_available_funds_fails_closed(self):
        with self.assertRaises(LiveAccountError):
            calculate_operational_buy_budget({"available_funds": -1.0}, strategy_cap=100_000.0)

    def test_invalid_safety_margin_fails_closed(self):
        with self.assertRaises(LiveAccountError):
            calculate_operational_buy_budget(
                {"available_funds": 100_000.0}, strategy_cap=100_000.0, safety_margin_pct=1.0
            )


if __name__ == "__main__":
    unittest.main()
