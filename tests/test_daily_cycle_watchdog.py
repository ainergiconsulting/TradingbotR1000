import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

APP=Path(__file__).resolve().parents[1]/'current_reference'/'PaperTradingR1000'
if str(APP) not in sys.path: sys.path.insert(0,str(APP))
import health_supervisor

class DailyCycleWatchdogTests(unittest.TestCase):
    def test_not_missed_before_grace(self):
        now=datetime(2026,9,18,13,40,tzinfo=timezone.utc) # 09:40 ET
        with patch.object(health_supervisor,'load_scheduler_state',return_value={'last_cycle_date':'2026-09-17'}):
            self.assertFalse(health_supervisor.strategy_cycle_watchdog(now)['missed'])
    def test_missed_after_grace(self):
        now=datetime(2026,9,18,13,44,tzinfo=timezone.utc) # 09:44 ET, > 09:43 deadline
        with patch.object(health_supervisor,'load_scheduler_state',return_value={'last_cycle_date':'2026-09-17'}):
            result=health_supervisor.strategy_cycle_watchdog(now)
        self.assertTrue(result['missed'])
        self.assertEqual(result['status'],'MISSED')
    def test_completed_today_not_missed(self):
        now=datetime(2026,9,18,14,0,tzinfo=timezone.utc)
        with patch.object(health_supervisor,'load_scheduler_state',return_value={'last_cycle_date':'2026-09-18'}):
            self.assertFalse(health_supervisor.strategy_cycle_watchdog(now)['missed'])
    def test_weekend_not_due(self):
        now=datetime(2026,9,19,14,0,tzinfo=timezone.utc)
        self.assertEqual(health_supervisor.strategy_cycle_watchdog(now)['status'],'NOT_DUE')

if __name__=='__main__': unittest.main()
