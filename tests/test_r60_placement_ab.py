"""Offline invariants for the placement A/B analyzer. No HA connection."""
import importlib.util
import unittest
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/'deploy'/'r60_placement_ab.py'
sys.path.insert(0,str(SCRIPT.parent))
spec=importlib.util.spec_from_file_location('r60_placement_ab',SCRIPT)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def make(t0, *, mac_success=1000, mac_failed=100, added=25, removed=25, cca=10, epoch='e'):
    x={key:0 for key in mod.FIELDS}
    x.update(MAC_TX_UNICAST_SUCCESS=mac_success,MAC_TX_UNICAST_FAILED=mac_failed,
             NEIGHBOR_ADDED=added,NEIGHBOR_REMOVED=removed,PHY_CCA_FAIL_COUNT=cca)
    return {'owner_epoch':epoch,'captured_utc':t0.isoformat(),'counters':x}

class WindowTest(unittest.TestCase):
    def setUp(self): self.now=datetime(2026,9,22,12,0,0,tzinfo=timezone.utc)
    def test_intentionally_unpowered_exclusions(self):
        for name in ('WorkroomTableRightDimmer','WorkroomTableLeftDimmer',
                     'BedroomBulb1','LivingRoomCircle1'):
            self.assertTrue(mod.intentionally_unpowered(name), name)
        for name in ('WorkroomSwitchLedsTable','HallBulb1','LivingRoomSocketHA',
                     'KitchenSocketFridge','BathroomSwitchRouter'):
            self.assertFalse(mod.intentionally_unpowered(name), name)

    def test_matched_delta_and_rates(self):
        a=make(self.now)
        b=make(self.now+timedelta(seconds=180),mac_success=2000,mac_failed=200,added=40,removed=40,cca=30)
        x=mod.window(a,b)
        self.assertEqual(x['mac_frames'],1100)
        self.assertAlmostEqual(x['mac_failure_fraction'],100/1100,places=5)
        self.assertEqual(x['neighbor_changes_per_min'],10)
        self.assertEqual(x['cca_failures_per_min'],round(20/3,3))
    def test_reject_counter_clear(self):
        a=make(self.now)
        b=make(self.now+timedelta(seconds=180),mac_failed=0)
        with self.assertRaisesRegex(ValueError,'reset_or_wrap'): mod.window(a,b)
    def test_reject_changed_owner(self):
        a=make(self.now)
        b=make(self.now+timedelta(seconds=180),mac_success=2000,mac_failed=200,epoch='different')
        with self.assertRaisesRegex(ValueError,'owner_restarted'): mod.window(a,b)
    def test_reject_short_window_or_low_traffic(self):
        a=make(self.now)
        b=make(self.now+timedelta(seconds=10),mac_success=1001,mac_failed=100)
        with self.assertRaisesRegex(ValueError,'invalid_window'):mod.window(a,b)
        b=make(self.now+timedelta(seconds=180),mac_success=1001,mac_failed=100)
        with self.assertRaisesRegex(ValueError,'too_few'):mod.window(a,b)

if __name__=='__main__': unittest.main()
