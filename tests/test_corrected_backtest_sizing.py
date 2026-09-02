from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = PROJECT_ROOT / "current_reference" / "PaperTradingR1000"
if str(RUNTIME_PATH) not in sys.path:
    sys.path.insert(0, str(RUNTIME_PATH))


def load_corrected_runner():
    path = PROJECT_ROOT / "backtests" / "r1000_max_positions_corrected" / "run_max_positions_backtest.py"
    spec = importlib.util.spec_from_file_location("r1000_corrected_backtest_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CorrectedBacktestSizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load_corrected_runner()

    def test_corrected_target_allocation_for_all_scenarios(self) -> None:
        current_nlv = 120_000.0
        expected = {
            5: 24_000.0,
            6: 20_000.0,
            7: 120_000.0 / 7,
            8: 15_000.0,
            9: 120_000.0 / 9,
            10: 12_000.0,
            12: 10_000.0,
            15: 8_000.0,
            20: 6_000.0,
        }
        for max_positions, target in expected.items():
            with self.subTest(max_positions=max_positions):
                sizing = self.runner.calculate_backtest_buy_sizing(
                    current_nlv=current_nlv,
                    available_cash=current_nlv,
                    fill_price=1.0,
                    max_positions=max_positions,
                )
                self.assertEqual(sizing.target_allocation, target)
                self.assertEqual(sizing.quantity, int(target))

    def test_full_target_purchase_rounds_to_whole_shares(self) -> None:
        sizing = self.runner.calculate_backtest_buy_sizing(
            current_nlv=100_000.0,
            available_cash=100_000.0,
            fill_price=333.0,
            max_positions=5,
        )
        self.assertEqual(sizing.target_allocation, 20_000.0)
        self.assertEqual(sizing.quantity, 60)
        self.assertEqual(sizing.purchase_notional, 19_980.0)
        self.assertLessEqual(sizing.total_purchase_cost, sizing.target_allocation)
        self.assertLessEqual(sizing.total_purchase_cost, sizing.available_cash)

    def test_residual_cash_can_create_smaller_final_position(self) -> None:
        sizing = self.runner.calculate_backtest_buy_sizing(
            current_nlv=100_000.0,
            available_cash=1_234.0,
            fill_price=100.0,
            max_positions=5,
        )
        self.assertEqual(sizing.target_allocation, 20_000.0)
        self.assertEqual(sizing.usable_allocation, 1_234.0)
        self.assertEqual(sizing.quantity, 12)
        self.assertEqual(sizing.total_purchase_cost, 1_200.0)

    def test_quantity_zero_when_one_share_is_not_affordable(self) -> None:
        sizing = self.runner.calculate_backtest_buy_sizing(
            current_nlv=100_000.0,
            available_cash=50.0,
            fill_price=100.0,
            max_positions=5,
        )
        self.assertEqual(sizing.quantity, 0)
        self.assertEqual(sizing.purchase_notional, 0)
        self.assertEqual(sizing.total_purchase_cost, 0)

    def test_transaction_costs_are_included_in_affordability(self) -> None:
        sizing = self.runner.calculate_backtest_buy_sizing(
            current_nlv=10_000.0,
            available_cash=2_000.0,
            fill_price=100.0,
            max_positions=5,
            transaction_cost=5.0,
        )
        self.assertEqual(sizing.target_allocation, 2_000.0)
        self.assertEqual(sizing.quantity, 19)
        self.assertEqual(sizing.purchase_notional, 1_900.0)
        self.assertEqual(sizing.total_purchase_cost, 1_905.0)
        self.assertLessEqual(sizing.total_purchase_cost, sizing.target_allocation)
        self.assertLessEqual(sizing.total_purchase_cost, sizing.available_cash)

    def test_no_negative_cash_no_leverage_in_sequential_same_day_buys(self) -> None:
        cash = 1_000.0
        position_value = 0.0
        fills = []
        for _ in range(3):
            current_nlv = cash + position_value
            sizing = self.runner.calculate_backtest_buy_sizing(
                current_nlv=current_nlv,
                available_cash=cash,
                fill_price=100.0,
                max_positions=2,
            )
            fills.append(sizing.quantity)
            cash -= sizing.total_purchase_cost
            position_value += sizing.purchase_notional
            self.assertGreaterEqual(cash, 0)
            self.assertLessEqual(sizing.total_purchase_cost, sizing.available_cash)
        self.assertEqual(fills, [5, 5, 0])
        self.assertEqual(cash, 0)
        self.assertEqual(position_value, 1_000.0)

    def test_max_positions_selection_remains_independently_enforced(self) -> None:
        candidates = [
            self.runner.EntryEvaluation("BBB", 10.0, 9.0, 11.0, 0.10, True, True),
            self.runner.EntryEvaluation("AAA", 10.0, 9.0, 11.0, 0.10, True, True),
        ]
        selection = self.runner.select_candidates(candidates, slots_available=1)
        self.assertEqual(len(selection.selected), 1)
        self.assertEqual(selection.selected[0].symbol, "AAA")
        self.assertEqual(len(selection.skipped), 1)

    def test_entry_ranking_and_exit_logic_match_shared_strategy_module(self) -> None:
        import strategy

        closes = [100.0 + index * 0.2 for index in range(220)]
        closes[-1] = 120.0
        dates = [f"2020{(index // 28) + 1:02d}{(index % 28) + 1:02d}" for index in range(220)]
        bars = self.runner.SymbolBars(
            symbol="TEST",
            dates=dates,
            opens=closes[:],
            highs=[value + 1 for value in closes],
            lows=[value - 1 for value in closes],
            closes=closes,
            volumes=[1000.0] * len(closes),
            source_path="synthetic",
            date_to_index={date: index for index, date in enumerate(dates)},
            sma200=self.runner.compute_sma(closes, strategy.APPROVED_PARAMETERS.moving_average_period),
            lower_band20=self.runner.compute_lower_band(
                closes,
                strategy.APPROVED_PARAMETERS.bollinger_period,
                strategy.APPROVED_PARAMETERS.bollinger_std_dev,
            ),
            ranking_return150=self.runner.compute_ranking_return(closes, strategy.APPROVED_PARAMETERS.ranking_lookback_days),
            rsi2=self.runner.compute_rsi(closes, strategy.APPROVED_PARAMETERS.rsi_period),
        )
        runner_eval = self.runner.entry_evaluation_for("TEST", bars, len(closes) - 1)
        strategy_eval = strategy.evaluate_entry_candidate("TEST", closes)
        self.assertIsNotNone(runner_eval)
        assert runner_eval is not None
        self.assertTrue(math.isclose(runner_eval.moving_average, strategy_eval.moving_average))
        self.assertTrue(math.isclose(runner_eval.lower_bollinger_band, strategy_eval.lower_bollinger_band))
        self.assertTrue(math.isclose(runner_eval.ranking_return, strategy_eval.ranking_return))
        self.assertEqual(strategy.exit_decision(59.0, 61.0, 3).reason, "rsi_cross_above_60")

    def test_operational_strategy_and_broker_sizing_remain_unchanged(self) -> None:
        import automated_broker
        import strategy

        self.assertEqual(strategy.investable_capital_value(100_000.0), 70_000.0)
        self.assertEqual(strategy.position_allocation_value(100_000.0), 14_000.0)

        scan = {
            "cycle_id": "cycle-test",
            "strategy_version": strategy.STRATEGY_VERSION,
            "configuration_sha256": "abc",
            "order_plans": [
                {
                    "symbol": "AAPL",
                    "limit_price": 100.0,
                    "allocation_value": 14_000.0,
                }
            ],
            "signal_dates": {"AAPL": "20260721"},
        }
        broker_context = {
            "account_values": {
                "net_liquidation": 100_000.0,
                "cash": 100_000.0,
                "available_funds": 100_000.0,
                "buying_power": 100_000.0,
            }
        }
        intent = automated_broker._buy_intents(scan, broker_context)[0]
        self.assertEqual(intent["quantity"], 140.0)
        self.assertEqual(intent["estimated_notional"], 14_000.0)
        self.assertEqual(intent["rejection_reason"], "")


if __name__ == "__main__":
    unittest.main()
