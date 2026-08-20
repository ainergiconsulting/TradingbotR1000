import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import reporter


class ReporterTests(unittest.TestCase):
    def test_summary_counts_scan_evidence(self):
        summary = reporter.build_summary(
            {
                "timestamp_utc": "2026-07-21T00:00:00Z",
                "evaluated_candidates": [{"symbol": "AAA"}],
                "selected_candidates": [{"symbol": "AAA"}],
                "skipped_candidates": [],
                "order_plans": [{"symbol": "AAA"}],
                "exit_signals": [],
                "available_slots": 1,
                "ranking_applied": False,
                "execute_orders": False,
            }
        )

        self.assertEqual(summary["selected"], 1)
        self.assertEqual(summary["orders"], 1)


if __name__ == "__main__":
    unittest.main()
