"""Synthetic offline ZNP bytes, never a live coordinator query."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "deploy" / "p10_neighbor_capacity.py"
spec = importlib.util.spec_from_file_location("p10_neighbor_capacity_raw", PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def reply(start, count, total=60, *, status=0, source=0):
    records = []
    for i in range(start, start + count):
        records.append(b"\xaa" * 8 + (i+1).to_bytes(8, "little") +
                       (i+1).to_bytes(2, "little") + b"\x05\x00\x01\x9b")
    payload = source.to_bytes(2, "little") + bytes((status, total, start, count)) + b"".join(records)
    header = bytes((len(payload), 0x45, 0xb1))
    fcs = 0
    for value in header + payload:
        fcs ^= value
    return (b"\xfe" + header + payload + bytes((fcs,))).hex()


class OfflineZnpTests(unittest.TestCase):
    def test_sixty_router_records_across_six_raw_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "synthetic.hex"
            image.write_bytes(b"test")
            pages = [{"znp_frame_hex": reply(i, 10)} for i in range(0, 60, 10)]
            doc = {"scope": "isolated-disposable-network", "observer_role": "coordinator",
                   "source": "ZDO-Mgmt_Lqi_rsp", "radio_image_sha256": mod.digest(image),
                   "captures": [{"timestamp_utc": "2026-09-23T12:00:00Z", "pages": pages}]}
            result = mod.snapshot_report(doc, image, 60)
            self.assertEqual(result["observed_router_entries_peak"], 60)
            self.assertFalse(result["atomic_simultaneity_verified"])
            self.assertNotIn("0100000000000000", json.dumps(result))

    def test_cli_decodes_raw_pages_not_just_import_time_unit_tests(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "synthetic.hex"
            image.write_bytes(b"test")
            doc = {"scope": "isolated-disposable-network", "observer_role": "coordinator",
                   "source": "ZDO-Mgmt_Lqi_rsp", "radio_image_sha256": mod.digest(image),
                   "captures": [{"timestamp_utc": "2026-09-23T12:00:00Z",
                                 "pages": [{"znp_frame_hex": reply(i, 10, 30)} for i in (0, 10, 20)]}]}
            capture_file = Path(folder) / "isolated.json"
            capture_file.write_text(json.dumps(doc), encoding="utf-8")
            result = subprocess.run([sys.executable, str(PATH), "snapshot", str(capture_file),
                                     "--image", str(image), "--min-neighbor", "27"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["observed_router_entries_peak"], 30)

    def test_reject_corrupt_fcs_and_wrong_source(self):
        good = bytes.fromhex(reply(0, 1, total=1))
        bad = good[:-1] + bytes((good[-1] ^ 1,))
        with self.assertRaisesRegex(ValueError, "checksum"):
            mod.decode_znp_mgmt_lqi(bad.hex())
        with self.assertRaisesRegex(ValueError, "isolated coordinator"):
            mod.decode_znp_mgmt_lqi(reply(0, 1, total=1, source=42))

    def test_reject_truncated_and_wrong_command(self):
        raw = bytes.fromhex(reply(0, 1, total=1))
        for invalid in (raw[:-1].hex(), "fe00450144", "not-hex"):
            with self.assertRaises(ValueError):
                mod.decode_znp_mgmt_lqi(invalid)

    def test_reject_status_failure_and_pagination_churn(self):
        first = {"znp_frame_hex": reply(0, 10, 60)}
        second = {"znp_frame_hex": reply(10, 10, 59)}
        with self.assertRaises(ValueError):
            mod.decode_capture({"timestamp_utc": "2026-09-23T12:00:00Z", "pages": [first, second]})
        with self.assertRaises(ValueError):
            mod.decode_capture({"timestamp_utc": "2026-09-23T12:00:00Z",
                                "pages": [{"znp_frame_hex": reply(0, 1, total=1, status=1)}]})

    def test_reject_manually_overridden_raw_frame_fields(self):
        with self.assertRaisesRegex(ValueError, "only znp_frame_hex"):
            mod.decode_capture({"timestamp_utc": "2026-09-23T12:00:00Z",
                                "pages": [{"znp_frame_hex": reply(0, 1, total=1), "status": 0}]})


if __name__ == "__main__":
    unittest.main()
