from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware"
if str(FIRMWARE) not in sys.path:
    sys.path.insert(0, str(FIRMWARE))

from patch_p011_xncp import PROFILE
import verify_build as core


class ProfileVariantTests(unittest.TestCase):
    def test_p011_canonical_profile_hash_is_stable_and_keeps_mcast26(self):
        raw = json.dumps(PROFILE, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "1501697486ba4b36ffcd05b7657005fcb6c74ff55f1e23830e5a458758658fca")
        self.assertEqual(PROFILE["resources"]["SL_ZIGBEE_MULTICAST_TABLE_SIZE"], 26)
        self.assertEqual(PROFILE["resources"]["SL_ZIGBEE_BROADCAST_TABLE_SIZE"], 64)

    def test_p011_template_uses_current_sdk_xncp_info_symbol(self):
        text = (FIRMWARE / "p011_identity_template.c").read_text(encoding="utf-8")
        self.assertIn("void sl_zigbee_af_xncp_get_xncp_information(", text)
        self.assertNotIn("sl_zigbee_af_xncp_get_xncp_information_cb", text)
        self.assertIn("#define P011_XNCP_ENTRY __attribute__((used, noinline, externally_visible))", text)
        self.assertIn("P011_XNCP_ENTRY void sl_zigbee_af_xncp_get_xncp_information(", text)
        self.assertIn("P011_XNCP_ENTRY sl_status_t sl_zigbee_af_xncp_incoming_custom_frame_cb(", text)
        verifier = (FIRMWARE / "verify_variants.py").read_text(encoding="utf-8")
        self.assertIn("sl_zigbee_af_xncp_get_xncp_information", verifier)
        self.assertNotIn("sl_zigbee_af_xncp_get_xncp_information_cb", verifier)

    def test_readelf_symbols_keeps_defined_duplicate_over_zero_sized_entry(self):
        raw = (
            "  1: 00000000     0 FUNC    GLOBAL DEFAULT  UND sl_zigbee_af_xncp_incoming_custom_frame_cb\n"
            "  2: 08001234    48 FUNC    GLOBAL DEFAULT    1 sl_zigbee_af_xncp_incoming_custom_frame_cb\n"
        )
        with mock.patch.object(core, "_readelf", return_value=raw):
            symbols = core.readelf_symbols(Path("dummy.out"))
        self.assertEqual(symbols["sl_zigbee_af_xncp_incoming_custom_frame_cb"], 48)

    def test_p013_patch_changes_only_multicast_on_p009_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src" / "zigbee_ncp"
            src.mkdir(parents=True)
            slcp = src / "zigbee_ncp.slcp"
            before = """  - name: SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE
    value: 512
  - name: SL_ZIGBEE_BROADCAST_TABLE_SIZE
    value: 64
  - name: SL_ZIGBEE_KEY_TABLE_SIZE
    value: 12
  - name: SL_ZIGBEE_MULTICAST_TABLE_SIZE
    value: 26
"""
            slcp.write_text(before, encoding="utf-8")
            subprocess.run([sys.executable, str(FIRMWARE / "patch_p013_multicast.py"), str(root)], check=True, capture_output=True, text=True)
            after = slcp.read_text(encoding="utf-8")
            self.assertEqual(after.count("value: 32"), 1)
            self.assertIn("SL_ZIGBEE_MULTICAST_TABLE_SIZE\n    value: 32", after)
            self.assertIn("SL_ZIGBEE_BROADCAST_TABLE_SIZE\n    value: 64", after)
            self.assertIn("SL_ZIGBEE_KEY_TABLE_SIZE\n    value: 12", after)
            self.assertIn("SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE\n    value: 512", after)

    def test_p013_patch_rejects_non_p009_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src" / "zigbee_ncp"
            src.mkdir(parents=True)
            (src / "zigbee_ncp.slcp").write_text("SL_ZIGBEE_MULTICAST_TABLE_SIZE\n    value: 26\n", encoding="utf-8")
            cp = subprocess.run([sys.executable, str(FIRMWARE / "patch_p013_multicast.py"), str(root)], capture_output=True, text=True)
            self.assertNotEqual(cp.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
