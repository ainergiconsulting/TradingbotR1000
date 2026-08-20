import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import gateway_status


class GatewayStatusTests(unittest.TestCase):
    def test_socket_check_is_read_only_status(self):
        status = gateway_status.check_socket(timeout_seconds=0.01)

        self.assertIn("socket_reachable", status)
        self.assertIn("host", status)
        self.assertIn("port", status)


if __name__ == "__main__":
    unittest.main()
