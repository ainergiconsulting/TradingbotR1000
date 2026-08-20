import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import ibkr_flex_client


class FlexClientTests(unittest.TestCase):
    def test_unsupported_report_type_is_rejected(self):
        config = ibkr_flex_client.FlexConfig(
            enabled=True,
            token="token",
            activity_query_id="activity",
            trade_confirmation_query_id="trade",
        )

        with self.assertRaises(ibkr_flex_client.FlexConfigError):
            config.query_id_for("unknown")


if __name__ == "__main__":
    unittest.main()
