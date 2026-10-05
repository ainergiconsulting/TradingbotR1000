import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BOT=Path(__file__).resolve().parents[1]/"current_reference"/"PaperTradingR1000"
sys.path.insert(0,str(BOT))
import mobile_api


class MarketHoursConsistencyTests(unittest.TestCase):
    def test_one_server_time_is_shared_across_positions(self):
        fake_time=object()
        positions=[
            {"symbol":"ALL","contract":object()},
            {"symbol":"TIGO","contract":object()},
        ]
        seen=[]
        def fake_status(ib, contract, now=None, time_source=None, allow_server_time_lookup=True):
            seen.append((now,time_source,allow_server_time_lookup))
            return {"known":True,"trading_open":True,"liquid_open":True,"time_source":time_source}
        async def fake_broker_call(fn):
            return fn(object())
        with patch.object(mobile_api.core,"get_positions",return_value=positions), \
             patch.object(mobile_api.core,"get_ibkr_server_time",return_value=fake_time) as clock, \
             patch.object(mobile_api.core,"get_market_hours_status",side_effect=fake_status), \
             patch.object(mobile_api,"_broker_call",new=fake_broker_call):
            rows=asyncio.run(mobile_api.market_hours_all())
        self.assertEqual(clock.call_count,1)
        self.assertEqual(len(rows),2)
        self.assertTrue(all(x[0] is fake_time for x in seen))
        self.assertTrue(all(x[1]=="IBKR_SERVER_TIME" for x in seen))
        self.assertTrue(all(x[2] is False for x in seen))


if __name__=="__main__":
    unittest.main()
