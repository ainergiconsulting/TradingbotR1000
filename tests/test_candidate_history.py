import sys
import tempfile
import unittest
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import candidate_history


class CandidateHistoryTests(unittest.TestCase):
    def _scan(self):
        selected = [{
            "symbol": "AAA", "signal_day_close": 100.0, "ranking_return": 0.5,
            "trend_condition": True, "pullback_condition": True, "is_candidate": True,
        }]
        skipped = [{
            "symbol": f"X{i:02d}", "signal_day_close": 50.0 + i, "ranking_return": i / 100.0,
            "trend_condition": True, "pullback_condition": True, "is_candidate": True,
        } for i in range(12)]
        return {
            "timestamp_utc": "2026-09-21T13:28:00Z",
            "cycle_id": "cycle-1",
            "strategy_version": "1.1",
            "selected_candidates": selected,
            "skipped_candidates": skipped,
            "order_plans": [{"symbol": "AAA", "side": "BUY", "limit_price": 97.0, "quantity": 10, "signal_date": "20260918"}],
            "signal_dates": {f"X{i:02d}": "20260918" for i in range(12)},
        }

    def test_snapshot_includes_planned_and_top_ten_additional(self):
        snap = candidate_history.build_candidate_snapshot(self._scan(), scan_kind="REGULAR")
        planned = [x for x in snap["candidates"] if x["category"] == "PLANNED"]
        extra = [x for x in snap["candidates"] if x["category"] == "ADDITIONAL_CANDIDATE"]
        self.assertEqual([x["symbol"] for x in planned], ["AAA"])
        self.assertEqual(len(extra), 10)
        self.assertEqual(extra[0]["symbol"], "X11")
        self.assertEqual(extra[-1]["symbol"], "X02")
        self.assertEqual(extra[0]["limit_price_97pct"], round(61.0 * 0.97, 2))

    def test_submitted_order_is_recorded(self):
        report = {"broker_orders_transmitted": 1, "submitted_orders": [{"symbol": "AAA", "side": "BUY", "broker_status": "Submitted", "ibkr_order_id": 7}]}
        snap = candidate_history.build_candidate_snapshot(self._scan(), scan_kind="REGULAR", execution_report=report)
        planned = [x for x in snap["candidates"] if x["category"] == "PLANNED"][0]
        self.assertTrue(planned["broker_submitted"])
        self.assertEqual(planned["ibkr_order_id"], 7)

    def test_archive_is_idempotent_for_same_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            candidate_history.record_candidate_snapshot(self._scan(), scan_kind="REGULAR", path=path)
            candidate_history.record_candidate_snapshot(self._scan(), scan_kind="REGULAR", path=path)
            self.assertEqual(len([x for x in path.read_text().splitlines() if x.strip()]), 1)


if __name__ == "__main__":
    unittest.main()
