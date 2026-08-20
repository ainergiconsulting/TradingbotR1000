import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import startup_validation
import config


class IBKRApiPortPreflightTests(unittest.TestCase):
    def test_default_paper_gateway_port_is_4002(self):
        self.assertEqual(config.PORT, 4002)

    def test_startup_validation_does_not_require_live_gateway_by_default(self):
        result = startup_validation.validate_startup(require_universe_file=False, require_gateway=False)

        self.assertTrue(result["ok"])
        self.assertIn("ibkr_gateway", result)


if __name__ == "__main__":
    unittest.main()
