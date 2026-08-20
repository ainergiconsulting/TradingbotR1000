import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import order_safety


class LongOnlyOrderSafetyTests(unittest.TestCase):
    def test_rejects_sell_that_would_create_short_position(self):
        intent = order_safety.build_exit_intent("AAA", 2, "manual_test")

        with self.assertRaises(order_safety.LongOnlyOrderRejected):
            order_safety.validate_long_only_order(intent, current_position=1)

    def test_accepts_buy_and_covered_sell(self):
        order_safety.validate_long_only_order(order_safety.build_buy_intent("AAA", 1, 10.0, "test"))
        order_safety.validate_long_only_order(order_safety.build_exit_intent("AAA", 1, "test"), current_position=1)


if __name__ == "__main__":
    unittest.main()
