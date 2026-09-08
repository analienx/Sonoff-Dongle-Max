from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "firmware", ROOT / "deploy"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from verify_build_hardened import extract_eusart_rx_buffer
from p009_ownerproof import validate_owner_consistency
from p009_version import current_bridge_state_214, validate_approved_firmware


class ReleaseHardeningTests(unittest.TestCase):
    def test_rx_multiline_condition(self):
        self.assertEqual(extract_eusart_rx_buffer("""- name: SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE
  value: 512
  condition:
    - iostream_eusart
"""), 512)

    def test_rx_inline_condition(self):
        self.assertEqual(extract_eusart_rx_buffer("""- name: SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE
  value: '512'
  condition: [\"iostream_eusart\"]
"""), 512)

    def test_rx_scalar_condition(self):
        self.assertEqual(extract_eusart_rx_buffer("""- name: SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE
  value: 512
  condition: iostream_eusart
"""), 512)

    def test_rx_ambiguous_rejected(self):
        with self.assertRaises(SystemExit):
            extract_eusart_rx_buffer("""- name: SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE
  value: 128
  condition: [iostream_eusart]
- name: SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE
  value: 512
  condition:
    - iostream_eusart
""")

    def test_structured_stack_proof(self):
        snap = {
            "coordinator": {"type": "EmberZNet", "meta": {"majorrel": 9, "minorrel": 1, "maintrel": 1, "revision": "9.1.1"}},
            "identity": {"ezsp_version": 19},
            "version_lines": [],
        }
        proof = validate_approved_firmware(snap, "test")
        self.assertEqual(proof["ember_source"], "bridge/info")
        self.assertEqual(proof["ezsp"], 19)

    def test_log_fallback_is_explicit(self):
        snap = {"coordinator": {}, "identity": {}, "version_lines": ["EmberZNet 9.1.1", "EZSP version 19"]}
        proof = validate_approved_firmware(snap, "test")
        self.assertEqual(proof["ember_source"], "current-start-epoch-logs")
        self.assertEqual(proof["ezsp_source"], "current-start-epoch-logs")

    def test_wrong_structured_stack_rejected(self):
        snap = {
            "coordinator": {"type": "EmberZNet", "meta": {"majorrel": 9, "minorrel": 1, "maintrel": 0}},
            "identity": {"ezsp_version": 19},
            "version_lines": [],
        }
        with self.assertRaises(RuntimeError):
            validate_approved_firmware(snap, "test")

    def test_health_probe_source_uses_z2m_214_empty_request_and_nonretained_freshness(self):
        src = inspect.getsource(current_bridge_state_214)
        self.assertIn('c.publish(req,""', src)
        self.assertIn('healthRetain', src)
        self.assertIn('responseMs>=requestMs', src)
        self.assertNotIn('transaction:', src)

    def test_owner_consistency_accepts_one_exact_epoch(self):
        owner = {"container": "addon_z2m", "container_id": "a" * 64, "started_at": "2026-09-08T18:00:00Z"}
        snap = {"identity_evidence": {"owner": dict(owner)}}
        proof = validate_owner_consistency(snap, dict(owner), dict(owner))
        self.assertTrue(proof["same_before_embedded_after"])
        self.assertEqual(snap["identity_evidence"]["owner_consistency"]["container_id"], "a" * 64)

    def test_owner_consistency_rejects_restart_in_enrichment_window(self):
        before = {"container": "addon_z2m", "container_id": "a" * 64, "started_at": "2026-09-08T18:00:00Z"}
        embedded = dict(before)
        after = {"container": "addon_z2m", "container_id": "b" * 64, "started_at": "2026-09-08T18:00:02Z"}
        snap = {"identity_evidence": {"owner": embedded}}
        with self.assertRaises(RuntimeError):
            validate_owner_consistency(snap, before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
