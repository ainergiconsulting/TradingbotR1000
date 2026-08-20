import sys
import tempfile
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT_DIR))

import flex_normalizer


class FlexNormalizerTests(unittest.TestCase):
    def test_activity_report_normalizes_empty_flex_statement(self):
        xml = """<FlexQueryResponse><FlexStatements><FlexStatement fromDate="20260720" toDate="20260720" whenGenerated="20260721;120000"/></FlexStatements></FlexQueryResponse>"""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "statement.xml"
            output = Path(tmp) / "out"
            source.write_text(xml, encoding="utf-8")
            result = flex_normalizer.normalize_activity_report(source, output)

            self.assertTrue(result)
            self.assertTrue(all(path.exists() for path in result))


if __name__ == "__main__":
    unittest.main()
