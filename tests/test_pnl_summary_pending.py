import sys
import tempfile
import unittest
from pathlib import Path

BOT = Path(__file__).resolve().parents[1] / "current_reference" / "PaperTradingR1000"
sys.path.insert(0, str(BOT))

import flex_execution_ledger as ledger


class PendingPnlSummaryTests(unittest.TestCase):
    def test_pending_api_pnl_is_included_once_and_commission_is_negative(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "exec.sqlite3"
            with ledger.connect(db) as conn:
                conn.execute(
                    """INSERT INTO flex_executions(
                       source_key,trade_id,transaction_id,ib_exec_id,ib_order_id,account_id,
                       trade_date,date_time,symbol,side,quantity,price,proceeds,commission,
                       commission_currency,realized_pnl,order_type,open_close,asset_category,
                       conid,source_file,raw_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("trade:1","1","1","FLEX1","100","DU","20260922","20260922;100000",
                     "OLD","SELL",1,100,100,-2,"USD",50,"MKT","C","STK","1","x.xml","{}"),
                )
                conn.execute(
                    """INSERT INTO execution_notifications(
                       exec_id,first_seen_source,symbol,side,quantity,price,execution_time,
                       ib_order_id,commission,commission_currency,realized_pnl)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    ("API1","IBKR_API","NEW","SELL",10,90,"2026-09-23 13:30:00+00:00",
                     "200",3.5,"USD",-25),
                )
                conn.commit()

            summary = ledger.pnl_summary(path=db, start_date="2026-09-01")
            self.assertEqual(summary["confirmed_realized_pnl"], 50.0)
            self.assertEqual(summary["pending_realized_pnl"], -25.0)
            self.assertEqual(summary["realized_pnl_since_start"], 25.0)
            self.assertEqual(summary["confirmed_commissions"], -2.0)
            self.assertEqual(summary["pending_commissions"], -3.5)
            self.assertEqual(summary["commissions_since_start"], -5.5)

            history = ledger.order_history(path=db, start_date="2026-09-01", limit=20)
            pending = [x for x in history["orders"] if not x["flex_confirmed"]]
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["commission"], -3.5)

            # Once the same execution is Flex-confirmed, provisional P&L must vanish.
            with ledger.connect(db) as conn:
                conn.execute(
                    """INSERT INTO flex_executions(
                       source_key,trade_id,transaction_id,ib_exec_id,ib_order_id,account_id,
                       trade_date,date_time,symbol,side,quantity,price,proceeds,commission,
                       commission_currency,realized_pnl,order_type,open_close,asset_category,
                       conid,source_file,raw_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("trade:2","2","2","API1","200","DU","20260923","20260923;133000",
                     "NEW","SELL",10,90,900,-3.5,"USD",-25,"MKT","C","STK","2","y.xml","{}"),
                )
                conn.commit()
            summary2 = ledger.pnl_summary(path=db, start_date="2026-09-01")
            self.assertEqual(summary2["pending_realized_pnl"], 0.0)
            self.assertEqual(summary2["realized_pnl_since_start"], 25.0)
            self.assertEqual(summary2["commissions_since_start"], -5.5)


if __name__ == "__main__":
    unittest.main()
