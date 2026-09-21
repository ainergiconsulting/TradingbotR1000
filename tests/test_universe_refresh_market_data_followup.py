import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))
import operational_controller as oc


class UniverseRefreshFollowupTests(unittest.TestCase):
    def test_successful_universe_refresh_immediately_refreshes_market_data(self):
        # Verify the production source retains the invariant explicitly.
        source = Path(oc.__file__).read_text()
        block = source[source.index("if _universe_refresh_due():"):source.index("if _market_data_refresh_due():")]
        self.assertIn("universe_ok = run_weekly_universe_refresh()", block)
        self.assertIn("universe_data_ok = run_daily_market_data_refresh()", block)
        self.assertIn("if not universe_ok:", block)
        self.assertIn("else:", block)


if __name__ == "__main__":
    unittest.main()
