from __future__ import annotations

import unittest

from backtests.short_mean_reversion.short_execution import (
    cover_at_open,
    short_entry_limit_fill,
    short_stop_fill,
)


class ShortExecutionTests(unittest.TestCase):
    def test_short_entry_fills_at_open_when_open_above_limit(self) -> None:
        fill = short_entry_limit_fill(open_price=105.0, high_price=106.0, limit_price=103.0)

        self.assertTrue(fill.filled)
        self.assertEqual(fill.raw_price, 105.0)
        self.assertEqual(fill.reason, "short_entry_gap_above_limit")

    def test_short_entry_fills_at_limit_when_high_touches(self) -> None:
        fill = short_entry_limit_fill(open_price=100.0, high_price=104.0, limit_price=103.0)

        self.assertTrue(fill.filled)
        self.assertEqual(fill.raw_price, 103.0)
        self.assertEqual(fill.reason, "short_entry_limit_touched")

    def test_short_entry_expires_when_limit_not_touched(self) -> None:
        fill = short_entry_limit_fill(open_price=100.0, high_price=102.0, limit_price=103.0)

        self.assertFalse(fill.filled)
        self.assertEqual(fill.reason, "short_entry_expired_limit_not_touched")

    def test_stop_fills_at_open_on_gap_above_stop(self) -> None:
        fill = short_stop_fill(open_price=111.0, high_price=115.0, stop_price=108.0)

        self.assertTrue(fill.filled)
        self.assertEqual(fill.raw_price, 111.0)
        self.assertEqual(fill.reason, "stop_loss_gap_above_stop")

    def test_stop_fills_at_stop_when_high_touches(self) -> None:
        fill = short_stop_fill(open_price=104.0, high_price=109.0, stop_price=108.0)

        self.assertTrue(fill.filled)
        self.assertEqual(fill.raw_price, 108.0)
        self.assertEqual(fill.reason, "stop_loss_touched")

    def test_cover_slippage_is_adverse_to_short(self) -> None:
        fill = cover_at_open(100.0, slippage_bps=10.0, reason="rsi")

        self.assertTrue(fill.filled)
        self.assertAlmostEqual(fill.fill_price, 100.1)


if __name__ == "__main__":
    unittest.main()

