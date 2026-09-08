from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "firmware", ROOT / "deploy"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from verify_build_hardened import extract_eusart_rx_buffer
from p009_version import validate_approved_firmware


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
