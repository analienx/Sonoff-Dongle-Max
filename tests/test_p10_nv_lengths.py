"""Offline safety and evidence tests; no hardware or production traffic."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import p10_nv_lengths as nv


class P10NvLengthTests(unittest.TestCase):
    def test_only_four_allowlisted_readonly_commands(self):
        for command in ((0x21, 0x01), (0x21, 0x02), (0x27, 0x00)):
            self.assertTrue(nv.readonly_frame(*command).startswith(b"\xfe"))
        self.assertTrue(nv.readonly_frame(0x21, 0x32, b"\x01\x04\x00\x00\x00"))
        for command in ((0x21, 0x33), (0x21, 0x34), (0x21, 0x30), (0x21, 0x00), (0x25, 0x01)):
            with self.assertRaises(ValueError):
                nv.readonly_frame(*command)
        with self.assertRaises(ValueError):
            nv.readonly_frame(0x21, 0x32, b"\x01\x06\x00\x00\x00")
        with self.assertRaises(ValueError):
            nv.readonly_frame(0x21, 0x01, b"\x00")

    def test_idle_state_synthetic_validated(self):
        state = bytearray(14)
        nv.validated_idle_state(bytes(state))
        for offset, value in ((0, 1), (12, 9), (13, 1)):
            mutated = state.copy()
            mutated[offset] = value
            with self.assertRaises(ValueError):
                nv.validated_idle_state(bytes(mutated))
        with self.assertRaises(ValueError):
            nv.validated_idle_state(b"\x00" * 13)

    def test_contiguous_400_slots_proven_by_length_metadata(self):
        def fake_query(_ser, c0, c1, payload, timeout=2.5):
            self.assertEqual((c0, c1), (0x21, 0x32))
            self.assertEqual(payload[:3], b"\x01\x04\x00")
            slot = int.from_bytes(payload[3:5], "little")
            return (20 if slot < 400 else 0).to_bytes(4, "little")
        with patch.object(nv, "query", side_effect=fake_query):
            result = nv.scan_lengths(object(), 420)
        self.assertEqual(result["provisioned_tclk_nv_slots"], 400)
        self.assertEqual(result["first_missing_index"], 400)
        self.assertTrue(result["upper_boundary_observed"])
        self.assertEqual(result["neighbor_table_capacity"], "NOT_MEASURED")
        self.assertFalse(result["proves_network_migration"])

    def test_noncontiguous_or_unexpected_length_refused(self):
        for lengths in ([20, 0, 20], [20, 16, 0]):
            def fake_query(_ser, *args, **kwargs):
                item = fake_query.index
                fake_query.index += 1
                return lengths[item].to_bytes(4, "little")
            fake_query.index = 0
            with patch.object(nv, "query", side_effect=fake_query):
                with self.assertRaises(ValueError):
                    nv.scan_lengths(object(), 2)

    def test_short_response_refused(self):
        with patch.object(nv, "query", return_value=b"\x14"):
            with self.assertRaises(ValueError):
                nv.scan_lengths(object(), 400)


if __name__ == "__main__":
    unittest.main()
