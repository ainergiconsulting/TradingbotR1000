import inspect
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "current_reference"
sys.path.insert(0, str(REFERENCE_DIR))

from PaperTradingR1000 import strategy


class TradingbotR1000StrategyCoreTests(unittest.TestCase):
    def test_approved_strategy_constants_match_final_specification(self):
        params = strategy.APPROVED_PARAMETERS

        self.assertEqual(params.universe, "Russell 1000 stocks")
        self.assertEqual(params.timeframe, "daily")
        self.assertEqual(params.investable_capital_pct, 0.70)
        self.assertEqual(params.liquidity_reserve_pct, 0.30)
        self.assertEqual(params.position_allocation_pct, 0.20)
        self.assertEqual(params.max_positions, 5)
        self.assertFalse(params.leverage_allowed)
        self.assertEqual(params.moving_average_period, 200)
        self.assertEqual(params.bollinger_period, 20)
        self.assertEqual(params.bollinger_std_dev, 2.5)
        self.assertEqual(params.buy_limit_multiplier, 0.97)
        self.assertEqual(params.ranking_lookback_days, 150)
        self.assertEqual(params.rsi_period, 2)
        self.assertEqual(params.rsi_exit_cross_level, 50.0)
        self.assertEqual(params.max_holding_trading_days, 10)

    def test_entry_requires_close_above_sma_and_below_lower_bollinger_band(self):
        closes = [100.0] * 180 + [140.0] * 19 + [120.0]

        result = strategy.evaluate_entry_candidate("AAA", closes)

        self.assertTrue(result.trend_condition)
        self.assertTrue(result.pullback_condition)
        self.assertTrue(result.is_candidate)
        self.assertGreater(result.signal_day_close, result.moving_average)
        self.assertLess(result.signal_day_close, result.lower_bollinger_band)

    def test_buy_limit_and_position_size_use_investable_capital(self):
        candidate = strategy.EntryEvaluation(
            symbol="AAA",
            signal_day_close=50.0,
            moving_average=45.0,
            lower_bollinger_band=55.0,
            ranking_return=0.25,
            trend_condition=True,
            pullback_condition=True,
        )

        plan = strategy.build_buy_order_plan(candidate, net_liquidation_value=100_000.0)

        self.assertEqual(plan.symbol, "AAA")
        self.assertEqual(plan.limit_price, 48.5)
        self.assertEqual(plan.investable_capital, 70_000.0)
        self.assertEqual(plan.liquidity_reserve, 30_000.0)
        self.assertEqual(plan.allocation_value, 14_000.0)
        self.assertEqual(plan.intended_session, "next_trading_day")

    def test_ranking_is_applied_only_when_candidates_exceed_slots(self):
        low = strategy.EntryEvaluation("LOW", 10, 9, 11, 0.10, True, True)
        high = strategy.EntryEvaluation("HIGH", 10, 9, 11, 0.30, True, True)

        no_ranking = strategy.select_candidates([low, high], slots_available=2)
        self.assertFalse(no_ranking.ranking_applied)
        self.assertEqual([item.symbol for item in no_ranking.selected], ["LOW", "HIGH"])

        ranked = strategy.select_candidates([low, high], slots_available=1)
        self.assertTrue(ranked.ranking_applied)
        self.assertEqual([item.symbol for item in ranked.selected], ["HIGH"])
        self.assertEqual([item.symbol for item in ranked.skipped], ["LOW"])

    def test_ranking_ties_at_cutoff_use_symbol_ascending(self):
        late_symbol = strategy.EntryEvaluation("ZZZ", 10, 9, 11, 0.20, True, True)
        early_symbol = strategy.EntryEvaluation("AAA", 10, 9, 11, 0.20, True, True)

        selection = strategy.select_candidates([late_symbol, early_symbol], slots_available=1)

        self.assertTrue(selection.ranking_applied)
        self.assertEqual([item.symbol for item in selection.selected], ["AAA"])
        self.assertEqual([item.symbol for item in selection.skipped], ["ZZZ"])

    def test_rsi_exit_requires_cross_and_time_exit_uses_ten_trading_days(self):
        self.assertTrue(strategy.is_rsi_exit_cross(50.0, 50.1))
        self.assertFalse(strategy.is_rsi_exit_cross(51.0, 55.0))

        rsi_exit = strategy.exit_decision(49.0, 51.0, holding_trading_days=3)
        self.assertTrue(rsi_exit.should_exit)
        self.assertEqual(rsi_exit.reason, "rsi_cross_above_50")
        self.assertEqual(rsi_exit.timing, "next_market_open")

        time_exit = strategy.exit_decision(20.0, 30.0, holding_trading_days=10)
        self.assertTrue(time_exit.should_exit)
        self.assertEqual(time_exit.reason, "time_exit_10_trading_days")
        self.assertEqual(time_exit.timing, "next_market_open")

        hold = strategy.exit_decision(20.0, 30.0, holding_trading_days=9)
        self.assertFalse(hold.should_exit)

    def test_rsi_values_are_computed_from_completed_daily_closes(self):
        previous_rsi, current_rsi = strategy.latest_rsi_cross_values([100.0, 99.0, 98.0, 101.0])

        self.assertLessEqual(previous_rsi, 50.0)
        self.assertGreater(current_rsi, 50.0)

    def test_slot_accounting_reserves_pending_buy_orders(self):
        self.assertEqual(strategy.available_slots(open_positions=3), 2)
        self.assertEqual(strategy.available_slots(open_positions=3, pending_buy_orders=2), 0)

    def test_strategy_core_does_not_encode_excluded_strategy_rules(self):
        source = inspect.getsource(strategy).lower()

        for forbidden in (
            "iwb",
            "adjusted_last",
            "market-on-open",
            "opg",
            "ranking persistence",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
