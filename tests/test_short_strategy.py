from __future__ import annotations

import math
import unittest

from backtests.short_mean_reversion.short_strategy import (
    BASELINE_CONFIG,
    ShortEntryEvaluation,
    ShortStrategyConfig,
    evaluate_short_entry_candidate,
    is_short_rsi_exit_cross,
    select_short_candidates,
    short_entry_limit_price,
    short_exit_signal_decision,
)


class ShortStrategyTests(unittest.TestCase):
    def test_short_entry_requires_downtrend_and_upper_band_overextension(self) -> None:
        closes = [100.0] * 180 + [70.0] * 19 + [90.0]

        result = evaluate_short_entry_candidate("AAA", closes, rsi=95.0)

        self.assertTrue(result.trend_condition)
        self.assertTrue(result.overextension_condition)
        self.assertTrue(result.is_candidate)
        self.assertLess(result.signal_day_close, result.moving_average)
        self.assertGreater(result.signal_day_close, result.upper_bollinger_band)

    def test_optional_entry_rsi_filter_is_separate_from_mirror_baseline(self) -> None:
        closes = [100.0] * 180 + [70.0] * 19 + [90.0]
        config = BASELINE_CONFIG.with_updates(entry_rsi_min=95.0)

        rejected = evaluate_short_entry_candidate("AAA", closes, rsi=94.0, config=config)
        accepted = evaluate_short_entry_candidate("AAA", closes, rsi=95.0, config=config)

        self.assertFalse(rejected.rsi_condition)
        self.assertFalse(rejected.is_candidate)
        self.assertTrue(accepted.rsi_condition)
        self.assertTrue(accepted.is_candidate)

    def test_short_ranking_uses_lowest_appreciation_then_symbol(self) -> None:
        high = ShortEntryEvaluation("ZZZ", 10, 12, 9, 0.30, None, True, True, True)
        low_late = ShortEntryEvaluation("BBB", 10, 12, 9, -0.20, None, True, True, True)
        low_early = ShortEntryEvaluation("AAA", 10, 12, 9, -0.20, None, True, True, True)

        selection = select_short_candidates([high, low_late, low_early], slots_available=2)

        self.assertTrue(selection.ranking_applied)
        self.assertEqual([item.symbol for item in selection.selected], ["AAA", "BBB"])
        self.assertEqual([item.symbol for item in selection.skipped], ["ZZZ"])

    def test_short_entry_limit_uses_premium_multiplier(self) -> None:
        self.assertTrue(math.isclose(short_entry_limit_price(100.0), 103.0))

    def test_short_rsi_exit_cross_and_time_exit(self) -> None:
        config = ShortStrategyConfig(exit_rsi_cross_level=40.0, max_holding_trading_days=10)

        self.assertTrue(is_short_rsi_exit_cross(45.0, 39.9, config))
        self.assertFalse(is_short_rsi_exit_cross(35.0, 30.0, config))

        rsi_exit = short_exit_signal_decision(45.0, 39.9, 3, config)
        self.assertTrue(rsi_exit.should_exit)
        self.assertEqual(rsi_exit.reason, "rsi_cross_below_40")

        time_exit = short_exit_signal_decision(80.0, 70.0, 10, config)
        self.assertTrue(time_exit.should_exit)
        self.assertEqual(time_exit.reason, "time_exit_10_trading_days")

        hold = short_exit_signal_decision(80.0, 70.0, 9, config)
        self.assertFalse(hold.should_exit)


if __name__ == "__main__":
    unittest.main()

