"""No-radio regression tests for issue #29 Phase A migration preparation."""
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / "deploy"


def load(name):
    spec = importlib.util.spec_from_file_location(name, BASE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load("p10_readonly")
audit = load("p10_firmware_audit")


class FakeSerial:
    def __init__(self, data):
        self.data = io.BytesIO(data)

    def read(self, n):
        return self.data.read(n)


def reply(cmd1, payload):
    header = bytes([len(payload), 0x61, cmd1])
    fcs = 0
    for value in header + payload:
        fcs ^= value
    return b"\xfe" + header + payload + bytes([fcs])


class P10ProbeTests(unittest.TestCase):
    def test_safe_commands_only(self):
        self.assertEqual(probe.frame(0x21, 0x02), bytes.fromhex("fe00210223"))
        for cmd0, cmd1 in ((0x21, 0x03), (0x25, 0x00)):
            with self.assertRaises(ValueError):
                probe.frame(cmd0, cmd1)
        with self.assertRaises(ValueError):
            probe.frame(0x21, 0x01, b"bad")

    def test_bad_checksum_and_unrelated_response_are_ignored(self):
        valid = reply(2, bytes([2, 1, 3, 0, 1, 0x41, 0x21, 0x35, 0x01]))
        wire = reply(1, b"\x03\x00") + valid[:-1] + bytes([valid[-1] ^ 1]) + valid
        self.assertEqual(probe.receive(FakeSerial(wire), (0x21, 2), probe.time.monotonic()+1), valid[4:-1])

    def test_version_requires_complete_payload(self):
        version = probe.version_details(bytes([2, 1, 3, 0, 1, 1, 2, 3, 4]))
        self.assertEqual(version["revision_raw_uint32"], 0x04030201)
        for length in (0, 4, 6, 8):
            with self.assertRaises(ValueError):
                probe.version_details(bytes(length))
    def test_refuse_non_usb_or_unconfirmed_port(self):
        with self.assertRaises(ValueError):
            probe.inspect("socket://example.org:6638", 115200, None, 0x1234, 0x5678)
        with self.assertRaises(ValueError):
            probe.inspect("COM4", 115200, "com4", 0x1234, 0x5678)
        with self.assertRaises(ValueError):
            probe.inspect("COM4", 115200, None)
        with patch.object(probe, "ports", return_value=[{"port": "COM4", "vid": 12, "pid": 34}]):
            with self.assertRaises(ValueError):
                probe.inspect("COM4", 115200, None, 99, 34)
            with self.assertRaises(ValueError):
                probe.inspect("COM5", 115200, None, 12, 34)

    def test_reject_usb_bridge_same_vid_pid_but_wrong_unit_identity(self):
        port = {"port": "COM4", "vid": 0x10c4, "pid": 0xea60,
                "serial_number": "NEW-P10", "location": "1-3"}
        with patch.object(probe, "ports", return_value=[port]):
            with self.assertRaisesRegex(ValueError, "serial number or bus location"):
                probe.inspect("COM4", 115200, None, 0x10c4, 0xea60)
            with self.assertRaisesRegex(ValueError, "serial number mismatch"):
                probe.inspect("COM4", 115200, None, 0x10c4, 0xea60, "OLD-SONOFF")
            with self.assertRaisesRegex(ValueError, "bus location mismatch"):
                probe.inspect("COM4", 115200, None, 0x10c4, 0xea60, None, "1-4")

    def test_immutable_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "capture.json"
            probe.save_exclusive(path, {"neighbor_capacity": "UNKNOWN"})
            with self.assertRaises(FileExistsError):
                probe.save_exclusive(path, {"neighbor_capacity": 50})

    def test_offline_image_hash_is_not_capacity_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fake.hex"
            path.write_bytes(b"sample")
            item = probe.artifact(path)
            self.assertEqual(item["sha256"], probe.hashlib.sha256(b"sample").hexdigest())
            self.assertIn("UNKNOWN", item["compiled_neighbor_capacity"])


class P10FirmwareTests(unittest.TestCase):
    def complete(self):
        digest = "a" * 64
        return {"name": "synthetic", "board": "SLZB-06P10", "role": "coordinator",
                "adapter": "zstack", "image": {"sha256": digest,
                "vendor_source": "https://example.org/image.hex", "version": "test",
                "board_revision": "synthetic-r1"},
                "capacities": {table: {"entries": 120, "proof": "exact-build",
                    "evidence_url": "https://example.org/manifest", "image_sha256": digest}
                    for table in audit.REQUIRED},
                "migration": "not-tested", "groupcast_passed": False}

    def verify(self, candidate):
        return audit.verify_candidate(candidate, target_board="SLZB-06P10",
                                      min_neighbor=60, min_tclk=100, actual_image_sha256="a" * 64)

    def test_phase_a_not_confused_with_later_migration(self):
        outcome = self.verify(self.complete())
        self.assertEqual(outcome["status"], "MANIFEST_FIELDS_COMPLETE_UNVERIFIED")
        self.assertFalse(outcome["production_migration_authorized"])
        self.assertEqual(outcome["groupcast_test"], "not-proven")

    def test_self_reported_manifest_without_image_bytes_is_blocked(self):
        result = audit.verify_candidate(self.complete(), target_board="SLZB-06P10",
                                        min_neighbor=60, min_tclk=100)
        self.assertEqual(result["status"], "BLOCKED")

    def test_wrong_board_and_unlinked_image_blocked(self):
        candidate = self.complete()
        candidate["board"] = "SLZB-MR4U"
        self.assertEqual(self.verify(candidate)["status"], "BLOCKED")
        candidate = self.complete()
        candidate["capacities"]["neighbor"]["image_sha256"] = "b" * 64
        self.assertEqual(self.verify(candidate)["status"], "BLOCKED")

    def test_bool_and_invalid_counts_fail_closed(self):
        for count in (True, 0, 26, "60", -1):
            candidate = self.complete()
            candidate["capacities"]["neighbor"]["entries"] = count
            self.assertEqual(self.verify(candidate)["status"], "BLOCKED")

    def test_missing_security_tables_fail_closed(self):
        candidate = self.complete()
        del candidate["capacities"]["link_keys"]
        self.assertEqual(self.verify(candidate)["status"], "BLOCKED")

    def test_missing_actual_image_fails_closed(self):
        candidate = self.complete()
        candidate["image"]["sha256"] = "deadbeef"
        self.assertEqual(self.verify(candidate)["status"], "BLOCKED")

    def test_cli_even_complete_manifest_exits_nonzero_without_verified_capacity(self):
        with tempfile.TemporaryDirectory() as folder:
            local_image = Path(folder) / "synthetic.hex"
            local_image.write_bytes(b"synthetic image only")
            digest = probe.hashlib.sha256(local_image.read_bytes()).hexdigest()
            candidate = self.complete()
            candidate["image"]["sha256"] = digest
            for value in candidate["capacities"].values():
                value["image_sha256"] = digest
            manifest = Path(folder) / "candidates.json"
            manifest.write_text(json.dumps({"candidates": [candidate]}), encoding="utf-8")
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                code = audit.main([str(manifest), "--target-board", "SLZB-06P10",
                                   "--image", str(local_image)])
            self.assertEqual(code, 4)
            self.assertIn("MANIFEST_FIELDS_COMPLETE_UNVERIFIED", output.getvalue())

    def test_manifest_unknown_fails_and_exit_nonzero(self):
        folder = Path(__file__).resolve().parents[1]
        manifest = folder / "docs" / "p10_firmware_candidates.json"
        with patch("sys.stdout", new_callable=io.StringIO):
            code = audit.main([str(manifest), "--target-board", "SLZB-06P10"])
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
