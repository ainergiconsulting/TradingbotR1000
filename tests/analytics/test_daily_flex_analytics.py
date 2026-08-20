import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from analytics.flex_analytics import excel_feeds, storage


class DailyFlexAnalyticsTests(unittest.TestCase):
    def test_excel_feed_data_is_independent_from_trading_runtime(self):
        conn = sqlite3.connect(":memory:")
        storage.init_schema(conn)
        conn.execute(
            "INSERT INTO daily_nav VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("2026-07-20", 1000.0, 1010.0, 4.0, 6.0, 10.0, -1.0),
        )
        conn.commit()

        feeds = excel_feeds.build_excel_feed_data(conn)

        self.assertEqual(feeds["daily_nav"][0]["ending_nav"], 1010.0)
        self.assertEqual(feeds["cumulative_return"][0]["cumulative_pnl"], 10.0)


if __name__ == "__main__":
    unittest.main()
