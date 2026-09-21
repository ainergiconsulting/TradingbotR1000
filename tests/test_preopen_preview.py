import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import config as cfg
import operational_controller
import trading_engine


class PreopenPreviewScheduleTests(unittest.TestCase):
    def test_preview_due_after_successful_same_day_refresh(self):
        now = datetime(2026, 9, 18, 20, 35, tzinfo=timezone.utc)  # Friday 16:35 ET
        with TemporaryDirectory() as tmp:
            state = Path(tmp)
            daily = state / "daily.json"
            preview = state / "preview.json"
            daily.write_text(json.dumps({
                "attempt_date_et": "2026-09-18",
                "status": "OK",
                "expected_latest_completed_session": "20260918",
            }))
            with patch.object(operational_controller, "MARKET_DATA_DAILY_STATE_FILE", daily), \
                 patch.object(cfg, "PREOPEN_PREVIEW_REPORT_FILE", preview):
                self.assertTrue(operational_controller._preopen_preview_due(now))

    def test_preview_not_due_before_refresh_or_on_weekend(self):
        monday = datetime(2026, 9, 21, 12, 20, tzinfo=timezone.utc)
        saturday = datetime(2026, 9, 19, 12, 50, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            state = Path(tmp)
            daily = state / "daily.json"
            preview = state / "preview.json"
            daily.write_text(json.dumps({
                "attempt_date_et": "2026-09-18",
                "status": "OK",
                "expected_latest_completed_session": "20260917",
            }))
            with patch.object(operational_controller, "MARKET_DATA_DAILY_STATE_FILE", daily), \
                 patch.object(cfg, "PREOPEN_PREVIEW_REPORT_FILE", preview):
                self.assertFalse(operational_controller._preopen_preview_due(monday))
                self.assertFalse(operational_controller._preopen_preview_due(saturday))

    def test_matching_preview_is_not_repeated(self):
        now = datetime(2026, 9, 18, 20, 35, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            state = Path(tmp)
            daily = state / "daily.json"
            preview = state / "preview.json"
            daily.write_text(json.dumps({
                "attempt_date_et": "2026-09-18",
                "status": "OK",
                "expected_latest_completed_session": "20260918",
            }))
            preview.write_text(json.dumps({
                "preview_trade_date_et": "2026-09-21",
                "market_data_latest_date": "20260918",
            }))
            with patch.object(operational_controller, "MARKET_DATA_DAILY_STATE_FILE", daily), \
                 patch.object(cfg, "PREOPEN_PREVIEW_REPORT_FILE", preview):
                self.assertFalse(operational_controller._preopen_preview_due(now))

    def test_preview_is_repeated_if_session_evidence_mismatches(self):
        now = datetime(2026, 9, 18, 20, 35, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            state = Path(tmp)
            daily = state / "daily.json"
            preview = state / "preview.json"
            daily.write_text(json.dumps({
                "attempt_date_et": "2026-09-18",
                "status": "OK",
                "expected_latest_completed_session": "20260918",
            }))
            preview.write_text(json.dumps({
                "preview_trade_date_et": "2026-09-21",
                "market_data_latest_date": "20260917",
            }))
            with patch.object(operational_controller, "MARKET_DATA_DAILY_STATE_FILE", daily), \
                 patch.object(cfg, "PREOPEN_PREVIEW_REPORT_FILE", preview):
                self.assertTrue(operational_controller._preopen_preview_due(now))

    def test_preview_command_is_separate_from_regular_scan_command(self):
        completed = type("Done", (), {"returncode": 0})()
        with patch.object(operational_controller.subprocess, "run", return_value=completed) as run:
            rc = operational_controller.run_preopen_preview_once(preview_for_session_et="2026-09-21")
        self.assertEqual(rc, 0)
        command = run.call_args.args[0]
        self.assertIn("--preview-only", command)
        self.assertIn("--preview-for-session-et", command)
        self.assertIn("2026-09-21", command)
        self.assertNotIn("--scan-once", command)


if __name__ == "__main__":
    unittest.main()




class PostCloseRefreshScheduleTests(unittest.TestCase):
    def test_refresh_not_due_before_1630_et(self):
        now = datetime(2026, 9, 18, 20, 29, tzinfo=timezone.utc)  # 16:29 ET
        with TemporaryDirectory() as tmp:
            state = Path(tmp) / "daily.json"
            with patch.object(operational_controller, "MARKET_DATA_DAILY_STATE_FILE", state):
                self.assertFalse(operational_controller._market_data_refresh_due(now))

    def test_refresh_due_at_1630_et_when_current_session_missing(self):
        now = datetime(2026, 9, 18, 20, 30, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            state = Path(tmp) / "daily.json"
            state.write_text(json.dumps({
                "attempt_date_et": "2026-09-18",
                "status": "OK",
                "expected_latest_completed_session": "20260917",
                "completed_at_utc": "2026-09-18T20:20:00Z",
            }))
            with patch.object(operational_controller, "MARKET_DATA_DAILY_STATE_FILE", state):
                self.assertTrue(operational_controller._market_data_refresh_due(now))

    def test_refresh_waits_five_minutes_before_retry_when_bar_not_ready(self):
        now = datetime(2026, 9, 18, 20, 33, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            state = Path(tmp) / "daily.json"
            state.write_text(json.dumps({
                "attempt_date_et": "2026-09-18",
                "status": "OK",
                "expected_latest_completed_session": "20260917",
                "completed_at_utc": "2026-09-18T20:31:00Z",
            }))
            with patch.object(operational_controller, "MARKET_DATA_DAILY_STATE_FILE", state):
                self.assertFalse(operational_controller._market_data_refresh_due(now))

    def test_refresh_not_due_after_current_session_confirmed(self):
        now = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            state = Path(tmp) / "daily.json"
            state.write_text(json.dumps({
                "attempt_date_et": "2026-09-18",
                "status": "OK",
                "expected_latest_completed_session": "20260918",
                "completed_at_utc": "2026-09-18T20:45:00Z",
            }))
            with patch.object(operational_controller, "MARKET_DATA_DAILY_STATE_FILE", state):
                self.assertFalse(operational_controller._market_data_refresh_due(now))

    def test_next_market_session_after_friday_is_monday(self):
        from datetime import date
        self.assertEqual(
            operational_controller._next_market_session_date(date(2026, 9, 18)),
            "2026-09-21",
        )

class PreopenPreviewControllerFlowTests(unittest.TestCase):
    def _stop_after_first_loop(self):
        calls = {"n": 0}

        def stop():
            calls["n"] += 1
            return calls["n"] > 1

        return stop

    def test_successful_refresh_triggers_preview_before_regular_cycle(self):
        events = []

        with patch.object(operational_controller, "is_authorized", return_value=True),              patch.object(operational_controller, "write_desired_running"),              patch.object(operational_controller, "write_controller_status"),              patch.object(operational_controller, "write_runtime_bot_status"),              patch.object(operational_controller, "write_runtime_health"),              patch.object(operational_controller, "write_heartbeat"),              patch.object(
                 operational_controller,
                 "runtime_summary",
                 return_value={
                     "next_strategy_cycle_utc": "2026-09-21T13:28:00Z",
                     "last_strategy_cycle_result": "not_run",
                     "last_strategy_cycle_utc": "",
                 },
             ),              patch.object(operational_controller, "_universe_refresh_due", return_value=False),              patch.object(operational_controller, "_market_data_refresh_due", return_value=True),              patch.object(
                 operational_controller,
                 "run_daily_market_data_refresh",
                 side_effect=lambda: events.append("refresh") or True,
             ),              patch.object(operational_controller, "_preopen_preview_due", return_value=True),              patch.object(
                 operational_controller,
                 "run_preopen_preview_once",
                 side_effect=lambda **kwargs: events.append("preview") or 0,
             ),              patch.object(
                 operational_controller,
                 "_handle_preopen_preview_success",
                 side_effect=lambda: events.append("alert"),
             ),              patch.object(operational_controller, "is_cycle_due", return_value=False),              patch.object(
                 operational_controller,
                 "stop_bot_requested",
                 side_effect=self._stop_after_first_loop(),
             ):
            rc = operational_controller.supervise()

        self.assertEqual(rc, 0)
        self.assertEqual(events[:3], ["refresh", "preview", "alert"])

    def test_preview_failure_does_not_replace_regular_cycle(self):
        with patch.object(operational_controller, "is_authorized", return_value=True),              patch.object(operational_controller, "write_desired_running"),              patch.object(operational_controller, "write_controller_status"),              patch.object(operational_controller, "write_runtime_bot_status"),              patch.object(operational_controller, "write_runtime_health"),              patch.object(operational_controller, "write_heartbeat"),              patch.object(
                 operational_controller,
                 "runtime_summary",
                 return_value={
                     "next_strategy_cycle_utc": "2026-09-21T13:28:00Z",
                     "last_strategy_cycle_result": "not_run",
                     "last_strategy_cycle_utc": "",
                 },
             ),              patch.object(operational_controller, "_universe_refresh_due", return_value=False),              patch.object(operational_controller, "_market_data_refresh_due", return_value=False),              patch.object(operational_controller, "_preopen_preview_due", return_value=True),              patch.object(operational_controller, "run_preopen_preview_once", return_value=2),              patch.object(operational_controller, "alert_engine_failure"),              patch.object(operational_controller, "is_cycle_due", return_value=True),              patch.object(operational_controller, "run_engine_once", return_value=0) as regular,              patch.object(
                 operational_controller,
                 "_read_json_file",
                 return_value={},
             ),              patch.object(
                 operational_controller,
                 "stop_bot_requested",
                 side_effect=[False, True],
             ):
            rc = operational_controller.supervise()

        self.assertEqual(rc, 0)
        regular.assert_called_once()


class PreviewEngineIsolationTests(unittest.TestCase):
    def test_preview_returns_before_wait_or_broker_processing(self):
        from contextlib import ExitStack

        fake_broker = {
            "timestamp_utc": "2026-09-21T12:45:00Z",
            "client_id": cfg.CLIENT_ID,
            "account_mode": "PAPER",
            "accounts": ["DU123"],
            "account_values": {
                "net_liquidation": 100000.0,
                "cash": 100000.0,
                "available_funds": 100000.0,
                "lookahead_available_funds": 100000.0,
                "buying_power": 400000.0,
            },
            "positions": [],
            "open_orders": [],
        }
        fake_scan = {
            "timestamp_utc": "2026-09-21T12:45:01Z",
            "cycle_id": "preview-cycle",
            "strategy_version": "test",
            "selected_candidates": [{"symbol": "AAA"}],
            "order_plans": [{
                "symbol": "AAA",
                "side": "BUY",
                "order_type": "LIMIT",
                "allocation_value": 19800.0,
                "limit_price": 99.0,
            }],
            "rejected_symbols": [],
            "order_submission": "disabled",
        }
        fake_market = {
            "closes_by_symbol": {"AAA": [100.0] * 200},
            "status_rows": [],
            "latest_date": "20260918",
            "timestamp_utc": "2026-09-21T12:44:00Z",
            "signal_dates": {"AAA": "20260918"},
        }
        fake_state = {"active_positions": {}, "pending_buy_orders": {}}

        with TemporaryDirectory() as tmp:
            preview_path = Path(tmp) / "preview.json"
            with ExitStack() as stack:
                stack.enter_context(patch.object(cfg, "PREOPEN_PREVIEW_REPORT_FILE", preview_path))
                stack.enter_context(patch.object(cfg, "CANDIDATE_HISTORY_FILE", Path(tmp) / "candidate_history.jsonl"))
                stack.enter_context(patch.object(cfg, "ensure_runtime_dirs"))
                stack.enter_context(patch.object(trading_engine, "write_runtime_health"))
                stack.enter_context(patch.object(trading_engine, "write_heartbeat"))
                stack.enter_context(patch.object(trading_engine, "log"))
                stack.enter_context(patch.object(
                    trading_engine,
                    "ensure_runtime_ready",
                    return_value={"effective_configuration_sha256": "abc"},
                ))
                collect = stack.enter_context(patch.object(
                    trading_engine,
                    "collect_live_account_context",
                    return_value=fake_broker,
                ))
                stack.enter_context(patch.object(
                    trading_engine,
                    "evaluate_investable_capital_control",
                    return_value={
                        "compliance": "OK",
                        "effective_investable_capital": 100000.0,
                        "reason": "",
                    },
                ))
                stack.enter_context(patch.object(
                    trading_engine,
                    "calculate_operational_buy_budget",
                    return_value={
                        "operational_buy_budget": 99000.0,
                        "ibkr_cash": 100000.0,
                        "ibkr_available_funds": 100000.0,
                        "ibkr_lookahead_available_funds": 100000.0,
                        "capital_safety_margin_pct": 0.01,
                    },
                ))
                stack.enter_context(patch.object(
                    trading_engine,
                    "load_universe_config",
                    return_value={
                        "source_path": "unused.csv",
                        "daily_bars_dir": "unused",
                        "symbol_column": "symbol",
                    },
                ))
                stack.enter_context(patch.object(
                    trading_engine,
                    "_resolve_project_path",
                    return_value=Path(tmp),
                ))
                stack.enter_context(patch.object(
                    trading_engine,
                    "load_universe_symbol_records",
                    return_value={"symbols": ["AAA"], "exclusions": []},
                ))
                stack.enter_context(patch.object(
                    trading_engine,
                    "load_daily_bar_data",
                    return_value=fake_market,
                ))
                stack.enter_context(patch.object(
                    trading_engine,
                    "rebuild_and_save",
                    return_value=fake_state,
                ))
                stack.enter_context(patch.object(trading_engine, "active_position_count", return_value=0))
                stack.enter_context(patch.object(trading_engine, "pending_buy_count", return_value=0))
                stack.enter_context(patch.object(trading_engine, "active_position_symbols", return_value=set()))
                stack.enter_context(patch.object(trading_engine, "pending_buy_symbols", return_value=set()))
                stack.enter_context(patch.object(trading_engine, "read_blocked_symbols", return_value=set()))
                stack.enter_context(patch.object(trading_engine, "read_ignored_symbols", return_value=set()))
                stack.enter_context(patch.object(trading_engine, "scan_from_closes", return_value=fake_scan))
                stack.enter_context(patch.object(trading_engine, "evaluate_exit_signals", return_value=[]))
                stack.enter_context(patch.object(trading_engine, "build_sell_order_plans", return_value=[]))
                wait = stack.enter_context(patch.object(
                    trading_engine,
                    "wait_until_order_transmission_time",
                    side_effect=AssertionError("preview reached 09:30 wait"),
                ))
                process = stack.enter_context(patch.object(
                    trading_engine,
                    "process_order_plan",
                    side_effect=AssertionError("preview reached broker processing"),
                ))

                result = trading_engine.run_scan_once(preview_only=True)

            self.assertTrue(preview_path.exists())

        self.assertTrue(result["preview_only"])
        self.assertEqual(result["broker_orders_transmitted"], 0)
        self.assertEqual(collect.call_args.kwargs["readonly"], True)
        wait.assert_not_called()
        process.assert_not_called()
