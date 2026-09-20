import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import telegram_commands


class TelegramMonitoringTests(unittest.TestCase):
    def test_status_renderer_is_read_only(self):
        text = telegram_commands.render_status()
        self.assertIn("TradingbotR1000 status", text)

    def test_render_portfolio_shows_pending_order_details(self):
        snapshot = {
            "account_mode": "PAPER",
            "timestamp_utc": "2026-09-03T13:43:11Z",
            "account_values": {
                "net_liquidation": 1000000.0,
                "cash": 1000000.0,
                "available_funds": 1000000.0,
                "lookahead_available_funds": 1000000.0,
                "buying_power": 4000000.0,
            },
            "positions": [],
            "open_orders": [
                {"symbol": "FAST", "action": "BUY", "quantity": "4272", "limit_price": "46.49", "status": "Submitted", "filled": "0", "remaining": "4272"},
                {"symbol": "SNOW", "action": "BUY", "quantity": "669", "limit_price": "296.66", "status": "Submitted", "filled": "100", "remaining": "569"},
            ],
        }
        with patch.object(telegram_commands, "collect_live_account_context", return_value=snapshot):
            with patch.object(telegram_commands, "evaluate", return_value={"effective_investable_capital": 1000000.0}):
                text = telegram_commands.render_portfolio()
        self.assertIn("Pending orders: 2", text)
        self.assertIn("FAST BUY", text)
        self.assertIn("Ordered: 4272 @ $46.49", text)
        self.assertIn("Filled: 0", text)
        self.assertIn("Pending: 4272", text)
        self.assertIn("SNOW BUY", text)
        self.assertIn("Filled: 100", text)
        self.assertIn("Pending: 569", text)


    def test_status_does_not_label_previous_day_buy_plan_current(self):
        from unittest.mock import patch
        import telegram_commands
        fake_status = {
            "runtime_health": {"strategy_engine_state": "IDLE"},
            "scan_report": {
                "timestamp_utc": "2026-09-16T13:28:53Z",
                "selected_candidates": [{"symbol": "BNY"}],
                "order_plans": [{"symbol": "BNY", "allocation_value": 1000, "limit_price": 150.03}],
                "sell_order_plans": [],
            },
        }
        fake_snapshot = {
            "account_values": {
                "net_liquidation": 1000000, "cash": 900000,
                "available_funds": 900000, "buying_power": 3600000,
                "lookahead_available_funds": 900000,
            },
            "positions": [], "open_orders": [], "account_mode": "PAPER",
        }
        class FakeDateTime:
            @classmethod
            def now(cls, tz=None):
                from datetime import datetime as real_datetime, timezone
                return real_datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)
            @classmethod
            def fromisoformat(cls, value):
                from datetime import datetime as real_datetime
                return real_datetime.fromisoformat(value)
        with patch.object(telegram_commands, "collect_runtime_status", return_value=fake_status),              patch.object(telegram_commands, "collect_live_account_context", return_value=fake_snapshot),              patch.object(telegram_commands, "datetime", FakeDateTime):
            text = telegram_commands.render_status()
        self.assertIn("Next-session plan: PENDING", text)
        self.assertIn("Selected today: N/A (not evaluated yet)", text)
        self.assertIn("Planned orders: 0", text)
        self.assertNotIn("BUY BNY", text)
        self.assertNotIn("STALE / NOT CURRENT", text)
        self.assertNotIn("PLANNED / CURRENTLY VALID:", text)

if __name__ == "__main__":
    unittest.main()


class TelegramPreviewMonitoringTests(unittest.TestCase):
    def test_status_shows_current_preopen_preview_details(self):
        fake_status = {
            "runtime_health": {"strategy_engine_state": "IDLE"},
            "scan_report": {
                "timestamp_utc": "2026-09-18T13:28:53Z",
                "selected_candidates": [],
                "order_plans": [],
                "sell_order_plans": [],
            },
        }
        fake_preview = {
            "preview_trade_date_et": "2026-09-21",
            "preview_created_at_utc": "2026-09-21T12:45:10Z",
            "market_data_latest_date": "20260918",
            "selected_candidates": [{"symbol": "AAA"}, {"symbol": "BBB"}],
            "order_plans": [
                {
                    "symbol": "AAA",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "allocation_value": 9700.0,
                    "limit_price": 97.0,
                },
                {
                    "symbol": "BBB",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "allocation_value": 4850.0,
                    "limit_price": 48.5,
                },
            ],
            "sell_order_plans": [],
        }
        fake_snapshot = {
            "account_values": {
                "net_liquidation": 1000000,
                "cash": 900000,
                "available_funds": 900000,
                "buying_power": 3600000,
                "lookahead_available_funds": 900000,
            },
            "positions": [],
            "open_orders": [],
            "account_mode": "PAPER",
        }

        class FakeDateTime:
            @classmethod
            def now(cls, tz=None):
                from datetime import datetime as real_datetime, timezone
                return real_datetime(2026, 9, 21, 12, 50, tzinfo=timezone.utc)

            @classmethod
            def fromisoformat(cls, value):
                from datetime import datetime as real_datetime
                return real_datetime.fromisoformat(value)

        with patch.object(telegram_commands, "collect_runtime_status", return_value=fake_status),              patch.object(telegram_commands, "collect_live_account_context", return_value=fake_snapshot),              patch.object(telegram_commands, "read_json", return_value=fake_preview),              patch.object(telegram_commands, "datetime", FakeDateTime):
            text = telegram_commands.render_status()

        self.assertIn("Next-session plan: READY", text)
        self.assertIn("For session ET: 2026-09-21", text)
        self.assertIn("Signal session: 20260918", text)
        self.assertIn("Selected today: 2", text)
        self.assertIn("Planned orders: 2", text)
        self.assertIn("Broker submitted: 0", text)
        self.assertIn("BUY AAA | qty 100 | LIMIT @ $97.00", text)
        self.assertIn("BUY BBB | qty 100 | LIMIT @ $48.50", text)
        self.assertIn("PLANNED / NOT YET SUBMITTED:", text)
