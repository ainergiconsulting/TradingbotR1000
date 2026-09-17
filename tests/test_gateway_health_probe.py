import sys, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
APP=Path(__file__).resolve().parents[1]/'current_reference'/'PaperTradingR1000'
if str(APP) not in sys.path: sys.path.insert(0,str(APP))
import gateway_status

class GatewayHealthProbeTests(unittest.TestCase):
    def test_health_probe_is_readonly_and_restores_logger(self):
        fake=MagicMock()
        fake.isConnected.return_value=True
        fake.managedAccounts.return_value=[]
        fake.accountSummary.return_value=[]
        fake.positions.return_value=[]
        fake.portfolio.return_value=[]
        fake.openTrades.return_value=[]
        fake.reqCurrentTime.return_value=None
        lock=MagicMock()
        with patch.object(gateway_status,'IB',return_value=fake), \
             patch.object(gateway_status,'_acquire_probe_lock',return_value=lock), \
             patch.object(gateway_status,'_release_probe_lock'), \
             patch.object(gateway_status,'collect_ibkr_market_hours',return_value={}):
            result=gateway_status.collect_live_api_evidence('127.0.0.1',4002)
        self.assertTrue(result['connected'])
        kwargs=fake.connect.call_args.kwargs
        self.assertTrue(kwargs['readonly'])

if __name__=='__main__': unittest.main()
