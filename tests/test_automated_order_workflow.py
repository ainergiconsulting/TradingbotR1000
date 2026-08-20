import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import automated_broker
import automated_order_store
import config
import investable_capital_control
import live_account
import reconciliation
import strategy_scheduler


class AutomatedOrderWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.old_paths = {
            "AUTOMATED_ORDERS_FILE": config.AUTOMATED_ORDERS_FILE,
            "AUTOMATED_EXECUTION_REPORT_FILE": config.AUTOMATED_EXECUTION_REPORT_FILE,
            "STATE_FILE": config.STATE_FILE,
            "RECONCILIATION_REPORT_FILE": config.RECONCILIATION_REPORT_FILE,
            "SCHEDULER_STATE_FILE": config.SCHEDULER_STATE_FILE,
            "INVESTABLE_CAPITAL_CONTROL_FILE": config.INVESTABLE_CAPITAL_CONTROL_FILE,
            "EXECUTE_ORDERS": config.EXECUTE_ORDERS,
        }
        config.AUTOMATED_ORDERS_FILE = self.base / "automated_orders.json"
        config.AUTOMATED_EXECUTION_REPORT_FILE = self.base / "automated_execution_report.json"
        config.STATE_FILE = self.base / "bot_state.json"
        config.RECONCILIATION_REPORT_FILE = self.base / "reconciliation_report.json"
        config.SCHEDULER_STATE_FILE = self.base / "strategy_scheduler_state.json"
        config.INVESTABLE_CAPITAL_CONTROL_FILE = self.base / "investable_capital_control.json"
        config.EXECUTE_ORDERS = False

    def tearDown(self):
        for key, value in self.old_paths.items():
            setattr(config, key, value)
        self.tmp.cleanup()

    def _scan(self):
        return {
            "timestamp_utc": "2026-07-23T13:35:00Z",
            "cycle_id": "cycle-1",
            "strategy_version": "1.1",
            "configuration_sha256": "abc123",
            "market_data_latest_date": "20260722",
            "signal_dates": {"AAA": "20260722"},
            "order_plans": [
                {
                    "symbol": "AAA",
                    "limit_price": 48.5,
                    "allocation_value": 14000.0,
                    "signal_date": "20260722",
                }
            ],
            "sell_order_plans": [],
        }

    def _broker_context(self):
        return {
            "account_mode": "PAPER",
            "account_values": {
                "net_liquidation": 100000.0,
                "cash": 50000.0,
                "available_funds": 50000.0,
                "buying_power": 200000.0,
            },
            "positions": [],
            "open_orders": [],
        }

    def test_dry_run_persists_intent_once_across_restart(self):
        first = automated_broker.process_order_plan(self._scan(), self._broker_context(), transmit=False)
        second = automated_broker.process_order_plan(self._scan(), self._broker_context(), transmit=False)
        store = automated_order_store.load_store()

        self.assertEqual(first["broker_orders_transmitted"], 0)
        self.assertTrue(first["proof_no_broker_order_transmitted"])
        self.assertEqual(len(store["orders"]), 1)
        self.assertEqual(store["orders"][0]["broker_status"], "NotTransmitted")
        self.assertEqual(store["orders"][0]["quantity"], 288.0)
        self.assertEqual(second["duplicate_preventions"][0]["reason"], "persisted_dry_run_intent")

    def test_insufficient_cash_rejects_order_without_transmission(self):
        context = self._broker_context()
        context["account_values"]["cash"] = 10.0

        report = automated_broker.process_order_plan(self._scan(), context, transmit=False)

        self.assertEqual(report["rejected_orders"][0]["reason"], "insufficient_cash_or_buying_power")
        self.assertEqual(automated_order_store.load_store()["orders"][0]["broker_status"], "Rejected")

    def test_existing_open_order_prevents_duplicate_submission(self):
        context = self._broker_context()
        context["open_orders"] = [
            {
                "symbol": "AAA",
                "action": "BUY",
                "status": "Submitted",
                "order": {"action": "BUY"},
                "orderStatus": {"status": "Submitted"},
            }
        ]

        report = automated_broker.process_order_plan(self._scan(), context, transmit=False)

        self.assertEqual(report["duplicate_preventions"][0]["reason"], "current_ibkr_open_order")
        self.assertEqual(report["broker_orders_transmitted"], 0)

    def test_persisted_submitted_order_prevents_same_signal_after_config_change(self):
        intent = automated_broker.build_intended_orders(self._scan(), self._broker_context())[0]
        row = automated_order_store.upsert_order_intent(intent, broker_status="Submitted")
        automated_order_store.update_order_status(order_key=row["order_key"], broker_status="Submitted", ibkr_order_id=77)
        changed_scan = self._scan()
        changed_scan["configuration_sha256"] = "different"

        report = automated_broker.process_order_plan(changed_scan, self._broker_context(), transmit=False)

        self.assertEqual(report["duplicate_preventions"][0]["reason"], "persisted_automated_order_same_signal")

    def test_invalid_manual_investable_capital_blocks_buy_intent_only(self):
        scan = self._scan()
        scan["investable_capital_control"] = {
            "compliance": "INVALID - IC EXCEEDS NLV",
            "reason": "manual_investable_capital_exceeds_live_nlv",
        }

        report = automated_broker.process_order_plan(scan, self._broker_context(), transmit=False)

        self.assertEqual(report["rejected_orders"][0]["reason"], "manual_investable_capital_exceeds_live_nlv")

    def test_investable_capital_manual_and_auto_modes(self):
        manual = investable_capital_control.set_manual(50000, live_net_liquidation=100000.0)
        manual_result = investable_capital_control.evaluate(100000.0, manual)

        auto = investable_capital_control.set_auto()
        auto_result = investable_capital_control.evaluate(100000.0, auto)

        self.assertEqual(manual_result["mode"], "MANUAL")
        self.assertEqual(manual_result["effective_investable_capital"], 50000.0)
        self.assertEqual(auto_result["mode"], "AUTO")
        self.assertEqual(auto_result["effective_investable_capital"], 70000.0)

    def test_broker_status_transitions_are_persisted(self):
        intent = automated_broker.build_intended_orders(self._scan(), self._broker_context())[0]
        row = automated_order_store.upsert_order_intent(intent, broker_status="PendingSubmit")

        automated_order_store.update_order_status(
            order_key=row["order_key"],
            broker_status="PartiallyFilled",
            ibkr_order_id=123,
            perm_id=456,
            filled_quantity=100,
            remaining_quantity=188,
            average_fill_price=48.4,
        )
        automated_order_store.update_order_status(
            order_key=row["order_key"],
            broker_status="Filled",
            filled_quantity=288,
            remaining_quantity=0,
            average_fill_price=48.35,
        )

        stored = automated_order_store.load_store()["orders"][0]
        self.assertEqual(stored["broker_status"], "Filled")
        self.assertEqual(stored["ibkr_order_id"], 123)
        self.assertEqual(stored["perm_id"], 456)
        self.assertEqual(stored["filled_quantity"], 288.0)
        self.assertEqual(stored["remaining_quantity"], 0.0)

    def test_cancellation_and_rejection_statuses_are_persisted(self):
        intent = automated_broker.build_intended_orders(self._scan(), self._broker_context())[0]
        row = automated_order_store.upsert_order_intent(intent, broker_status="PreSubmitted")

        automated_order_store.update_order_status(
            order_key=row["order_key"],
            broker_status="Cancelled",
            cancellation_reason="operator_cancelled",
        )
        automated_order_store.update_order_status(
            order_key=row["order_key"],
            broker_status="Rejected",
            rejection_reason="broker_rejected",
        )

        stored = automated_order_store.load_store()["orders"][0]
        self.assertEqual(stored["broker_status"], "Rejected")
        self.assertEqual(stored["cancellation_reason"], "operator_cancelled")
        self.assertEqual(stored["rejection_reason"], "broker_rejected")

    def test_reconciliation_updates_automated_orders_from_broker_evidence(self):
        intent = automated_broker.build_intended_orders(self._scan(), self._broker_context())[0]
        row = automated_order_store.upsert_order_intent(intent, broker_status="PendingSubmit")
        automated_order_store.update_order_status(order_key=row["order_key"], broker_status="Submitted", ibkr_order_id=77, perm_id=88)

        updates = reconciliation.reconcile_automated_orders(
            {
                "open_orders": [
                    {
                        "order": {"orderId": "77", "permId": "88"},
                        "orderStatus": {"status": "Submitted", "filled": "0", "remaining": "288", "avgFillPrice": "0"},
                    }
                ],
                "executions": [
                    {
                        "execution": {
                            "orderId": "77",
                            "permId": "88",
                            "shares": "144",
                            "price": "48.25",
                        }
                    }
                ],
            }
        )
        stored = automated_order_store.load_store()["orders"][0]

        self.assertEqual(updates["open_order_updates"], 1)
        self.assertEqual(updates["execution_updates"], 1)
        self.assertEqual(stored["broker_status"], "PartiallyFilled")
        self.assertEqual(stored["filled_quantity"], 144.0)
        self.assertEqual(stored["remaining_quantity"], 144.0)

    def test_scheduler_next_cycle_skips_weekends(self):
        friday_after_cycle = datetime(2026, 7, 24, 20, 0, tzinfo=timezone.utc)

        next_cycle = strategy_scheduler.next_cycle_time(friday_after_cycle, {})

        self.assertEqual(next_cycle.astimezone(strategy_scheduler.NY_TZ).strftime("%Y-%m-%d %H:%M"), "2026-07-27 09:35")

    def test_scheduler_skips_observed_market_holiday(self):
        before_independence_observed = datetime(2026, 7, 2, 20, 0, tzinfo=timezone.utc)

        next_cycle = strategy_scheduler.next_cycle_time(before_independence_observed, {})

        self.assertEqual(next_cycle.astimezone(strategy_scheduler.NY_TZ).strftime("%Y-%m-%d %H:%M"), "2026-07-06 09:35")

    def test_live_account_validation_fails_closed_for_unknown_or_stale_evidence(self):
        snapshot = {
            "timestamp_utc": "2000-01-01T00:00:00Z",
            "account_mode": "UNKNOWN",
            "account_values": {
                "net_liquidation": 100000.0,
                "cash": 50000.0,
                "available_funds": 50000.0,
                "buying_power": 200000.0,
            },
        }

        with self.assertRaises(live_account.LiveAccountError):
            live_account.validate_live_account_snapshot(snapshot, max_age_seconds=999999)

        snapshot["account_mode"] = "PAPER"
        with self.assertRaises(live_account.LiveAccountError):
            live_account.validate_live_account_snapshot(snapshot, max_age_seconds=0)

    def test_live_account_collection_surfaces_ibkr_disconnection(self):
        original = live_account.connect
        try:
            def disconnected(*_args, **_kwargs):
                raise ConnectionError("gateway unavailable")

            live_account.connect = disconnected
            with self.assertRaises(ConnectionError):
                live_account.collect_live_account_context()
        finally:
            live_account.connect = original


if __name__ == "__main__":
    unittest.main()
