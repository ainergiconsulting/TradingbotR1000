from __future__ import annotations

import unittest

from backtests.short_mean_reversion.short_accounting import (
    ShortPosition,
    apply_borrow_cost,
    calculate_short_sizing,
    cover_short,
    mark_portfolio,
    open_short,
)
from backtests.short_mean_reversion.short_strategy import ShortStrategyConfig


class ShortAccountingTests(unittest.TestCase):
    def test_open_short_increases_cash_and_creates_liability(self) -> None:
        config = ShortStrategyConfig(commission_bps=0.0)

        cash, position = open_short(
            cash=1_000.0,
            symbol="AAA",
            quantity=10,
            fill_price=20.0,
            entry_date="20200102",
            entry_signal_date="20200101",
            entry_index=1,
            ranking_return=-0.2,
            sector="Tech",
            config=config,
        )
        mark = mark_portfolio(cash=cash, positions={"AAA": position}, prices={"AAA": 20.0})

        self.assertEqual(cash, 1_200.0)
        self.assertEqual(position.signed_quantity, -10)
        self.assertEqual(mark.short_liability, 200.0)
        self.assertEqual(mark.equity, 1_000.0)

    def test_profitable_cover_realises_short_pnl(self) -> None:
        config = ShortStrategyConfig()
        cash, position = open_short(
            cash=1_000.0,
            symbol="AAA",
            quantity=10,
            fill_price=20.0,
            entry_date="20200102",
            entry_signal_date="20200101",
            entry_index=1,
            ranking_return=-0.2,
            sector="Tech",
            config=config,
        )

        cash, trade = cover_short(
            cash=cash,
            position=position,
            cover_price=18.0,
            cover_date="20200103",
            cover_signal_date="20200102",
            cover_index=2,
            exit_reason="rsi",
            config=config,
        )

        self.assertEqual(cash, 1_020.0)
        self.assertEqual(float(trade["pnl"]), 20.0)
        self.assertEqual(float(trade["return_pct"]), 0.10)

    def test_losing_cover_realises_negative_short_pnl(self) -> None:
        config = ShortStrategyConfig()
        cash, position = open_short(
            cash=1_000.0,
            symbol="AAA",
            quantity=10,
            fill_price=20.0,
            entry_date="20200102",
            entry_signal_date="20200101",
            entry_index=1,
            ranking_return=-0.2,
            sector="Tech",
            config=config,
        )

        cash, trade = cover_short(
            cash=cash,
            position=position,
            cover_price=22.0,
            cover_date="20200103",
            cover_signal_date="20200102",
            cover_index=2,
            exit_reason="stop",
            config=config,
        )

        self.assertEqual(cash, 980.0)
        self.assertEqual(float(trade["pnl"]), -20.0)

    def test_borrow_cost_reduces_cash_and_trade_pnl(self) -> None:
        config = ShortStrategyConfig(borrow_fee_annual_pct=25.2)
        cash, position = open_short(
            cash=1_000.0,
            symbol="AAA",
            quantity=10,
            fill_price=20.0,
            entry_date="20200102",
            entry_signal_date="20200101",
            entry_index=1,
            ranking_return=-0.2,
            sector="Tech",
            config=config,
        )

        cash, cost = apply_borrow_cost(
            cash=cash,
            positions={"AAA": position},
            prices={"AAA": 20.0},
            annual_borrow_fee_pct=config.borrow_fee_annual_pct,
        )

        self.assertAlmostEqual(cost, 0.2)
        self.assertAlmostEqual(cash, 1_199.8)
        self.assertAlmostEqual(position.borrow_cost, 0.2)

    def test_sizing_respects_gross_short_exposure_cap(self) -> None:
        config = ShortStrategyConfig(position_gross_notional_pct=0.14, max_gross_short_exposure_pct=0.70)

        sizing = calculate_short_sizing(
            current_equity=100_000.0,
            current_gross_short_exposure=69_500.0,
            fill_price=100.0,
            config=config,
        )

        self.assertEqual(sizing.usable_notional, 500.0)
        self.assertEqual(sizing.quantity, 5)


if __name__ == "__main__":
    unittest.main()

