import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BOT = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT))

import trade_history


class TradeHistoryTests(unittest.TestCase):
    def test_closed_trade_pairing_uses_confirmed_flex_fills(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.sqlite3"
            conn = sqlite3.connect(db)
            conn.execute(
                """CREATE TABLE flex_executions(
                    trade_date TEXT, symbol TEXT, side TEXT, quantity REAL,
                    price REAL, realized_pnl REAL, commission REAL,
                    date_time TEXT, flex_confirmed INTEGER
                )"""
            )
            conn.executemany(
                "INSERT INTO flex_executions VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    ("20260901","AAA","BUY",100,10.0,0,-1,"20260901;100000",1),
                    ("20260902","AAA","SELL",100,11.0,100,-1,"20260902;100000",1),
                    ("20260903","BBB","BUY",50,20.0,0,-1,"20260903;100000",1),
                ],
            )
            conn.row_factory = sqlite3.Row
            rows = trade_history._flex_closed_trades(conn)
            conn.close()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["buy"]["symbol"], "AAA")
            self.assertEqual(rows[0]["sell"]["pnl"], 100)

    def test_list_trade_history_is_descriptive_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.sqlite3"
            conn = sqlite3.connect(db)
            conn.execute(
                """CREATE TABLE flex_executions(
                    trade_date TEXT, symbol TEXT, side TEXT, quantity REAL,
                    price REAL, realized_pnl REAL, commission REAL,
                    date_time TEXT, flex_confirmed INTEGER
                )"""
            )
            conn.commit()
            conn.close()
            result = trade_history.list_trade_history(path=db)
            self.assertFalse(result["research_or_simulation"])
            self.assertEqual(result["total_trades"], 0)

    def test_refresh_does_not_connect_to_ibkr_when_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.sqlite3"
            conn = sqlite3.connect(db)
            conn.execute(
                """CREATE TABLE flex_executions(
                    trade_date TEXT, symbol TEXT, side TEXT, quantity REAL,
                    price REAL, realized_pnl REAL, commission REAL,
                    date_time TEXT, flex_confirmed INTEGER
                )"""
            )
            conn.commit()
            conn.close()
            with patch.object(trade_history, "IB") as ib:
                result = trade_history.refresh_missing_trade_history(path=db)
            self.assertEqual(result["status"], "UP_TO_DATE")
            ib.assert_not_called()


if __name__ == "__main__":
    unittest.main()
