import importlib.util
import json
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "deploy" / "build_mg24_emergency_backups.py"
spec = importlib.util.spec_from_file_location("planner", MODULE)
planner = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(planner)

def backup(stack, fc=1000, devices=None, key="00"*16, ieee="00124b002d12b1fd"):
    internal = {"date":"x"}
    ss = {}
    if stack == "zstack":
        internal["znpVersion"] = 3
        ss={"zstack":{"tclk_seed":"11"*16}}
    else:
        internal["ezspVersion"] = 19
        ss={"ezsp":{"hashed_tclk":"22"*16}}
    return {
        "metadata":{"format":"zigpy/open-coordinator-backup","version":1,"source":"test","internal":internal},
        "stack_specific":ss,
        "coordinator_ieee":ieee,
        "pan_id":"45a1",
        "extended_pan_id":"d6167914c10a3a3a",
        "nwk_update_id":0,
        "security_level":5,
        "channel":11,
        "channel_mask":[11],
        "network_key":{"key":key,"sequence_number":0,"frame_counter":fc},
        "devices": devices or [],
    }

class Tests(unittest.TestCase):
    def test_build_preserves_identity_and_devices_only_on_p10(self):
        dev=[{"nwk_address":"1234","ieee_address":"aa"*8,"is_child":False,
              "link_key":{"key":"33"*16,"rx_counter":2,"tx_counter":3}}]
        src=backup("zstack",1000,dev)
        hist=backup("ember",500)
        ember,p10,plan=planner.build(src,hist,5000,10_000_000)
        self.assertEqual(planner.identity(src),planner.identity(ember))
        self.assertEqual(planner.identity(src),planner.identity(p10))
        self.assertEqual(ember["devices"],[])
        self.assertEqual(p10["devices"],dev)
        self.assertEqual(ember["network_key"]["frame_counter"],10_005_000)
        self.assertEqual(p10["network_key"]["frame_counter"],20_005_000)
        self.assertEqual(ember["metadata"]["internal"]["ezspVersion"],19)
        self.assertNotIn("znpVersion",ember["metadata"]["internal"])

    def test_floor_cannot_rewind_source(self):
        src=backup("zstack",7000)
        hist=backup("ember",500)
        ember,p10,plan=planner.build(src,hist,1000,100_000)
        self.assertEqual(plan["observed_counter_floor"],7000)
        self.assertGreater(ember["network_key"]["frame_counter"],7000)

    def test_identity_mismatch_fails(self):
        src=backup("zstack")
        hist=backup("ember",key="44"*16)
        with self.assertRaises(planner.PlanError):
            planner.build(src,hist,2000)

    def test_small_counter_lease_fails(self):
        with self.assertRaises(planner.PlanError):
            planner.build(backup("zstack"),backup("ember"),2000,99999)

if __name__=="__main__":
    unittest.main()
