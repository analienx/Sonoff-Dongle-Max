from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
if str(DEPLOY) not in sys.path:
    sys.path.insert(0, str(DEPLOY))

from p009_common import appended_logs, compare_identity, configure_remote, remote_argv, safe_identity_from_backup_doc
from p009_deploy import PHASE_ARMED, PHASE_IDENTITY, require_phase, runtime_readbacks


class P009Tests(unittest.TestCase):
    def test_safe_identity_hashes_key_without_returning_plaintext(self):
        key = "00112233445566778899aabbccddeeff"
        doc = {
            "metadata": {"format": "zigpy/open-coordinator-backup", "source": "test", "internal": {"ezspVersion": 19}},
            "coordinator_ieee": "fdb1122d004b1200",
            "pan_id": "45a1",
            "extended_pan_id": "d6167914c10a3a3a",
            "channel": 11,
            "network_key": {"key": key, "sequence_number": 0},
            "devices": [{"ieee_address": "00124b0000000001"}],
        }
        identity = safe_identity_from_backup_doc(doc)
        self.assertEqual(identity["network_key_sha256"], hashlib.sha256(bytes.fromhex(key)).hexdigest())
        self.assertNotIn(key, json.dumps(identity))
        self.assertEqual(identity["device_backup_entries"], 1)

    def test_remote_template_default_shape(self):
        configure_remote("ssh {host} {command}")
        self.assertEqual(remote_argv("ha", "echo ok"), ["ssh", "ha", "echo ok"])

    def test_remote_template_wrapper_shape(self):
        configure_remote("rtk proxy ssh {host} {command}")
        self.assertEqual(remote_argv("ha", "echo ok"), ["rtk", "proxy", "ssh", "ha", "echo ok"])

    def test_remote_template_requires_placeholders(self):
        with self.assertRaises(SystemExit):
            configure_remote("ssh ha")

    def test_appended_logs_exact_suffix(self):
        delta, exact = appended_logs("a\nb\n", "a\nb\nc\nd\n")
        self.assertTrue(exact)
        self.assertEqual(delta, "c\nd\n")

    def test_appended_logs_rotation_is_bounded(self):
        after = "\n".join(f"line-{i}" for i in range(700))
        delta, exact = appended_logs("old\n", after)
        self.assertFalse(exact)
        self.assertEqual(len(delta.splitlines()), 500)
        self.assertTrue(delta.startswith("line-200"))

    def test_runtime_readback_accepts_exact_policy(self):
        values = {
            "BROADCAST_TABLE_SIZE": 64,
            "NEW_BROADCAST_ENTRY_THRESHOLD": 48,
            "RETRY_QUEUE_SIZE": 16,
            "MTORR_FLOW_CONTROL": 1,
            "SUPPORTED_NETWORKS": 1,
            "SEND_MULTICASTS_TO_SLEEPY_ADDRESS": 0,
        }
        lines = [f"[P009 EZSP] {k} expected={v} actual={v} readStatus=OK" for k, v in values.items()]
        self.assertEqual(set(runtime_readbacks(lines)), set(values))

    def test_runtime_readback_rejects_mismatch(self):
        with self.assertRaises(SystemExit):
            runtime_readbacks(["[P009 EZSP] BROADCAST_TABLE_SIZE expected=64 actual=30 readStatus=OK"])

    def test_identity_compare_detects_drift(self):
        base = {"identity": {"coordinator_ieee": "aa", "pan_id": "bb", "extended_pan_id": "cc", "channel": 11, "network_key_sha256": "dd", "network_key_sequence_number": 0, "device_backup_entries": 104}}
        same = json.loads(json.dumps(base))
        self.assertEqual(compare_identity(base, same), [])
        changed = json.loads(json.dumps(base))
        changed["identity"]["channel"] = 15
        self.assertIn("channel", compare_identity(base, changed)[0])

    def test_phase_gate(self):
        require_phase({"phase": PHASE_ARMED}, PHASE_ARMED)
        with self.assertRaises(SystemExit):
            require_phase({"phase": PHASE_ARMED}, PHASE_IDENTITY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
