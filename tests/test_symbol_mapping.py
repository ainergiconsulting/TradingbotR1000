import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import symbol_mapping


class SymbolMappingTests(unittest.TestCase):
    def test_canonical_symbols_use_massive_file_format(self):
        self.assertEqual(symbol_mapping.canonical_symbol("BRKB"), "BRK.B")
        self.assertEqual(symbol_mapping.canonical_symbol("UHAL B"), "UHAL.B")
        self.assertEqual(symbol_mapping.historical_filename("BF-B"), "BF.B.csv")

    def test_ibkr_symbols_use_space_class_format(self):
        self.assertEqual(symbol_mapping.ibkr_symbol("BRK.B"), "BRK B")
        self.assertEqual(symbol_mapping.ibkr_symbol("LENB"), "LEN B")

    def test_ibkr_space_symbol_round_trips_to_canonical(self):
        self.assertEqual(symbol_mapping.canonical_symbol_from_ibkr("BRK B"), "BRK.B")
        self.assertEqual(symbol_mapping.canonical_symbol_from_ibkr("UHAL B"), "UHAL.B")

    def test_unresolved_ibkr_exclusions_are_centralized(self):
        self.assertEqual(symbol_mapping.exclusion_reason("HOLX"), "ibkr_unresolved_no_market_universe_symbol")
        self.assertTrue(symbol_mapping.is_excluded("NSA"))


if __name__ == "__main__":
    unittest.main()

