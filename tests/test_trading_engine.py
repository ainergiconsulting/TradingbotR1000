import sys
import unittest
import tempfile
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import trading_engine


class TradingEngineTests(unittest.TestCase):
    def test_load_universe_symbols_reads_iwb_holdings_format(self):
        content = "\n".join(
            [
                "metadata",
                "",
                "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date",
                "BRKB,BERKSHIRE HATHAWAY INC CLASS B,Financials,Equity,,,,,,US,NYSE,USD,,USD,",
                "UHALB,U-HAUL HOLDING COMPANY,Industrials,Equity,,,,,,US,NYSE,USD,,USD,",
                "CASH,CASH,Cash and/or Derivatives,Cash,,,,,,US,,USD,,USD,",
                "AAPL,APPLE INC,Information Technology,Equity,,,,,,US,NASDAQ,USD,,USD,",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "IWB_holdings.csv"
            path.write_text(content, encoding="utf-8")

            self.assertEqual(trading_engine.load_universe_symbols(path, "Ticker"), ["BRK.B", "UHAL.B", "AAPL"])

    def test_load_universe_symbol_records_reports_unresolved_ibkr_exclusions(self):
        content = "\n".join(
            [
                "metadata",
                "",
                "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date",
                "HOLX,HOLOGIC INC,Health Care,Equity,,,,,,US,NO MARKET (E.G. UNLISTED),USD,,USD,",
                "AAPL,APPLE INC,Information Technology,Equity,,,,,,US,NASDAQ,USD,,USD,",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "IWB_holdings.csv"
            path.write_text(content, encoding="utf-8")

            records = trading_engine.load_universe_symbol_records(path, "Ticker")

        self.assertEqual(records["symbols"], ["AAPL"])
        self.assertEqual(records["exclusions"][0]["symbol"], "HOLX")
        self.assertEqual(records["exclusions"][0]["reason"], "ibkr_unresolved_no_market_universe_symbol")

    def test_scan_builds_r1000_order_plan_without_extra_filters(self):
        candidate_closes = [100.0] * 180 + [140.0] * 19 + [120.0]
        noncandidate_closes = [100.0] * 199 + [90.0]

        scan = trading_engine.scan_from_closes(
            {"AAA": candidate_closes, "BBB": noncandidate_closes},
            net_liquidation_value=100000.0,
            open_positions=0,
        )

        self.assertEqual([row["symbol"] for row in scan["selected_candidates"]], ["AAA"])
        self.assertEqual(scan["order_plans"][0]["limit_price"], 116.39999999999999)
        self.assertEqual(scan["investable_capital"], 70000.0)
        self.assertEqual(scan["liquidity_reserve"], 30000.0)
        self.assertEqual(scan["order_plans"][0]["allocation_value"], 14000.0)
        self.assertEqual(scan["order_submission"], "disabled")

    def test_scan_can_size_from_operator_investable_capital_override(self):
        candidate_closes = [100.0] * 180 + [140.0] * 19 + [120.0]

        scan = trading_engine.scan_from_closes(
            {"AAA": candidate_closes},
            net_liquidation_value=100000.0,
            effective_investable_capital=50000.0,
            open_positions=0,
        )

        self.assertEqual(scan["investable_capital"], 50000.0)
        self.assertEqual(scan["liquidity_reserve"], 50000.0)
        self.assertEqual(scan["order_plans"][0]["allocation_value"], 10000.0)

    def test_scan_excludes_active_and_pending_symbols_from_new_buy_plan(self):
        candidate_closes = [100.0] * 180 + [140.0] * 19 + [120.0]

        scan = trading_engine.scan_from_closes(
            {"AAA": candidate_closes, "BBB": candidate_closes},
            net_liquidation_value=100000.0,
            open_positions=1,
            pending_buy_orders=1,
            active_symbols={"AAA"},
            pending_buy_symbols={"AAA"},
        )

        self.assertEqual(scan["reserved_position_slots"], 1)
        self.assertEqual(scan["available_slots"], 4)
        self.assertEqual([row["symbol"] for row in scan["selected_candidates"]], ["BBB"])
        self.assertEqual(scan["rejected_symbols"][0]["reason"], "active_position_or_pending_buy")

    def test_exit_signals_are_derived_from_rsi_or_holding_days(self):
        signals = trading_engine.evaluate_exit_signals(
            {
                "AAA": {"previous_rsi2": 49, "current_rsi2": 51, "holding_trading_days": 3},
                "BBB": {"previous_rsi2": 20, "current_rsi2": 30, "holding_trading_days": 10},
            }
        )

        self.assertEqual([row["reason"] for row in signals], ["rsi_cross_above_50", "time_exit_10_trading_days"])

    def test_exit_signals_can_compute_rsi2_from_completed_daily_bars(self):
        signals = trading_engine.evaluate_exit_signals(
            {"AAA": {"holding_trading_days": 3}},
            {"AAA": [100.0, 99.0, 98.0, 101.0]},
        )

        self.assertEqual(signals[0]["symbol"], "AAA")
        self.assertEqual(signals[0]["reason"], "rsi_cross_above_50")

    def test_scan_reports_short_histories_as_insufficient_history(self):
        scan = trading_engine.scan_from_closes(
            {"AAA": [100.0] * 20},
            net_liquidation_value=100000.0,
            open_positions=0,
        )

        self.assertEqual(scan["rejected_symbols"], [{"symbol": "AAA", "reason": "insufficient_history"}])

    def test_daily_bar_loader_reports_missing_and_stale_data(self):
        with tempfile.TemporaryDirectory() as directory:
            bars = Path(directory)
            (bars / "AAA.csv").write_text(
                "date,open,high,low,close,volume\n20260720,1,1,1,1,100\n",
                encoding="utf-8",
            )
            (bars / "BBB.csv").write_text(
                "date,open,high,low,close,volume\n20260721,1,1,1,1,100\n",
                encoding="utf-8",
            )

            result = trading_engine.load_daily_bar_data(["AAA", "BBB", "CCC"], bars)

        reasons = {row["symbol"]: row["reason"] for row in result["status_rows"]}
        self.assertEqual(reasons["AAA"], "stale_market_data")
        self.assertEqual(reasons["CCC"], "missing_market_data")
        self.assertIn("BBB", result["closes_by_symbol"])
        self.assertNotIn("AAA", result["closes_by_symbol"])


if __name__ == "__main__":
    unittest.main()
