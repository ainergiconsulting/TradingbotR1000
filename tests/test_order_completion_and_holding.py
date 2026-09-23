import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BOT = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT))

import automated_order_store
import flex_execution_ledger
import order_completion_alerts
from position_lifecycle import holding_trading_days


class HoldingDaysTests(unittest.TestCase):
    def test_entry_session_counts_as_day_one(self):
        dates = ["20260909","20260910","20260911","20260914","20260915",
                 "20260916","20260917","20260918","20260921","20260922"]
        self.assertEqual(holding_trading_days("20260909", dates), 10)


class OrderCompletionTests(unittest.TestCase):
    def test_alert_only_after_entire_order_is_filled_and_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "exec.sqlite3"
            store_path = Path(tmp) / "orders.json"
            order = {
                "order_key": "k1", "symbol": "AAA", "side": "BUY", "quantity": 100.0,
                "ibkr_order_id": 10, "submitted_at_utc": "2026-09-23T13:30:00Z",
                "broker_status": "Submitted", "status_history": [],
            }
            automated_order_store.save_store({"bot":"TradingbotR1000","orders":[order]}, store_path)

            def load():
                return automated_order_store.load_store(store_path)
            def save(data):
                return automated_order_store.save_store(data, store_path)
            def conn():
                return flex_execution_ledger.connect(db)

            def observe(exec_id, **kwargs):
                return flex_execution_ledger.observe_execution(exec_id, path=db, **kwargs)
            def mark(exec_id):
                return flex_execution_ledger.mark_execution_notified(exec_id, path=db)

            with patch.object(order_completion_alerts, "load_store", side_effect=load), \
                 patch.object(order_completion_alerts, "save_store", side_effect=save), \
                 patch.object(order_completion_alerts, "ledger_connect", side_effect=conn), \
                 patch.object(order_completion_alerts, "observe_execution", side_effect=observe), \
                 patch.object(order_completion_alerts, "mark_execution_notified", side_effect=mark), \
                 patch.object(order_completion_alerts, "alert_execution_filled") as alert:
                first = order_completion_alerts.process_execution(
                    exec_id="e1", symbol="AAA", side="BUY", quantity=40, price=10,
                    execution_time="2026-09-23 13:31:00+00:00", api_order_id="10", source="IBKR_API",
                )
                self.assertFalse(first)
                self.assertEqual(alert.call_count, 0)

                second = order_completion_alerts.process_execution(
                    exec_id="e2", symbol="AAA", side="BUY", quantity=60, price=11,
                    execution_time="2026-09-23 13:31:02+00:00", api_order_id="10", source="IBKR_API",
                )
                self.assertTrue(second)
                self.assertEqual(alert.call_count, 1)
                payload = alert.call_args.args[0]
                self.assertEqual(payload["quantity"], 100.0)
                self.assertAlmostEqual(payload["price"], 10.6)

                duplicate = order_completion_alerts.process_execution(
                    exec_id="e2", symbol="AAA", side="BUY", quantity=60, price=11,
                    execution_time="2026-09-23 13:31:02+00:00", api_order_id="10", source="IBKR_API",
                )
                self.assertFalse(duplicate)
                self.assertEqual(alert.call_count, 1)

                updated = automated_order_store.load_store(store_path)["orders"][0]
                self.assertEqual(updated["broker_status"], "Filled")
                self.assertEqual(updated["remaining_quantity"], 0.0)


if __name__ == "__main__":
    unittest.main()
