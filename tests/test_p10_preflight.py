"""Offline regression tests; never open serial ports or join networks."""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / "deploy"

def load(name):
    spec = importlib.util.spec_from_file_location(name, BASE / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

probe = load("p10_readonly")
audit = load("p10_firmware_audit")

class FakeSerial:
    def __init__(self, data):
        self.data = io.BytesIO(data)
    def read(self, n):
        return self.data.read(n)

def reply(cmd1, payload):
    h = bytes([len(payload), 0x61, cmd1])
    fcs = 0
    for c in h + payload:
        fcs ^= c
    return b"\xfe" + h + payload + bytes([fcs])

class P10ProbeTests(unittest.TestCase):
    def test_safe_commands_only(self):
        self.assertEqual(probe.frame(0x21, 0x02), bytes.fromhex("fe00210223"))
        for args in ((0x21, 0x03), (0x25, 0x00), (0x21, 0x01)):
            with self.assertRaises(ValueError):
                probe.frame(*args, data=b"bad")
        with self.assertRaises(ValueError):
            probe.frame(0x21, 0x03)
    def test_parser_skips_bad_fcs_and_unrelated_areq(self):
        good = reply(2, bytes([2, 1, 3, 0, 1, 0x41, 0x21, 0x35, 0x01]))
        bad = good[:-1] + bytes([good[-1] ^ 1])
        wire = reply(1, b"\x03\x00") + bad + good
        self.assertEqual(probe.receive(FakeSerial(wire), (0x21, 2), probe.time.monotonic()+1), good[4:-1])
    def test_version_and_truncation(self):
        v = probe.version_details(bytes([2, 1, 3, 0, 1, 1, 2, 3, 4]))
        self.assertEqual(v["revision_raw_uint32"], 0x04030201)
        with self.assertRaises(ValueError):
            probe.version_details(b"\x01\x02")
    def test_no_production_or_network_port(self):
        with self.assertRaises(ValueError):
            probe.inspect("socket://example.org:6638", 115200, None)
        with self.assertRaises(ValueError):
            probe.inspect("COM4", 115200, "com4")
    def test_immutable_output(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"capture.json"
            probe.save_exclusive(p, {"neighbor_capacity": "UNKNOWN"})
            with self.assertRaises(FileExistsError):
                probe.save_exclusive(p, {"neighbor_capacity": 50})
    def test_artifact_hash_not_claim_capacity(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"fake.hex"; p.write_bytes(b"sample")
            outcome = probe.artifact(p)
            self.assertEqual(outcome["sha256"], probe.hashlib.sha256(b"sample").hexdigest())
            self.assertIn("UNKNOWN", outcome["compiled_neighbor_capacity"])

class P10FirmwareTests(unittest.TestCase):
    def test_unverified_claim_does_not_pass(self):
        result = audit.report({"candidates": [{"name": "stock", "board": "SLZB-06P10",
            "role": "coordinator", "adapter": "zstack", "capacities": {"neighbor": {"entries": 60,
            "proof": "claimed"}}}]}, min_neighbor=50, min_tclk=100)
        self.assertEqual(result["results"][0]["status"], "BLOCKED")
    def test_complete_exact_build_requires_group_migration(self):
        c = {"name": "synthetic", "board": "SLZB-06P10", "role": "coordinator", "adapter": "zstack",
            "image": {"sha256": "deadbeef", "vendor_source": "synthetic"},
            "capacities": {k: {"entries": 120, "proof": "exact-build"} for k in audit.REQUIRED},
            "migration": "verified-on-same-stack", "groupcast_passed": True}
        self.assertEqual(audit.verify_candidate(c, min_neighbor=50, min_tclk=100)["status"],
                         "CANDIDATE_FOR_ISOLATED_VALIDATION")
        c["groupcast_passed"] = False
        self.assertEqual(audit.verify_candidate(c, min_neighbor=50, min_tclk=100)["status"], "BLOCKED")
    def test_insufficient_tclk(self):
        c = {"board": "SLZB-06P10", "role": "coordinator", "adapter": "zstack",
             "capacities": {k: {"entries": 60, "proof": "exact-build"} for k in audit.REQUIRED}}
        self.assertTrue(any("tclk" in s for s in audit.verify_candidate(c, min_neighbor=50,
            min_tclk=100)["reasons"]))

if __name__ == "__main__":
    unittest.main()
