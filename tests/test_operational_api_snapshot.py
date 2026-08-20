import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import operational_api_snapshot


class OperationalApiSnapshotTests(unittest.TestCase):
    def test_simple_contract_is_read_only_serialization(self):
        contract = type("Contract", (), {"symbol": "AAA", "secType": "STK", "currency": "USD"})()

        result = operational_api_snapshot.simple_contract(contract)

        self.assertEqual(result["symbol"], "AAA")
        self.assertEqual(result["secType"], "STK")


if __name__ == "__main__":
    unittest.main()
