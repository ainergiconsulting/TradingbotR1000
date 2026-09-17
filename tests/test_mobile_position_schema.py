import sys
from pathlib import Path
import unittest
APP=Path(__file__).resolve().parents[1]/"current_reference"/"PaperTradingR1000"
sys.path.insert(0,str(APP))
import mobile_api

class MobilePositionSchemaTests(unittest.TestCase):
    def test_camelcase_broker_fields_are_exposed_canonically(self):
        row=mobile_api._mobile_position_row({"symbol":"ABNB","quantity":"1176","averageCost":"169.305","marketPrice":"166.11","marketValue":"195354.4","unrealizedPNL":"-3748.28"})
        self.assertEqual(row["average_cost"],"169.305")
        self.assertEqual(row["market_price"],"166.11")
        self.assertEqual(row["market_value"],"195354.4")
        self.assertEqual(row["unrealized_pnl"],"-3748.28")
