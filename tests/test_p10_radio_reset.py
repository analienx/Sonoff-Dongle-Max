import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import p10_radio_reset as subject


def valid_info(revision=20240716):
    return {
        "model": "SLZB-MR4U",
        "coord_mode": 2,
        "sw_version": "v3.4.1.dev1",
        "radios": [
            {
                "chip_index": 0,
                "zb_hw": "EFR32MG26",
                "zb_version": 20260416,
                "zb_type": 2,
            },
            {
                "chip_index": 1,
                "zb_hw": "CC2674P10",
                "zb_version": revision,
                "zb_type": 0,
            },
        ],
    }


class R2ResetTests(unittest.TestCase):
    def common(self, **overrides):
        reset_calls = []
        probes = iter([
            {"ok": False, "revision": None},
            {"ok": False, "revision": None},
            {"ok": True, "revision": 20240716},
        ])
        args = dict(
            info=valid_info(),
            expected_index=1,
            expected_revision=20240716,
            execute=True,
            reason="terminal SYS ping failure",
            run_id="20261003T085500-r2",
            quiescent=lambda: {"addon_quiescent": True},
            identity=lambda: {
                "interface": "02",
                "model": "SMLIGHT_SLZB-MR4U",
                "serial_sha256": "a" * 64,
            },
            pre_probe=lambda: next(probes),
            reset_once=lambda: reset_calls.append("reset"),
            post_probe=lambda: next(probes),
            sleep=lambda _: None,
        )
        args.update(overrides)
        return args, reset_calls

    def test_execute_calls_reset_exactly_once_and_verifies(self):
        args, calls = self.common()
        result = subject.recover(**args)
        self.assertEqual(calls, ["reset"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["verify_attempt"], 2)
        self.assertEqual(result["target"]["chip"], "CC2674P10")

    def test_failed_verification_never_retries_reset(self):
        calls = []
        args, _ = self.common(
            pre_probe=lambda: {"ok": False},
            post_probe=lambda: {"ok": False},
            reset_once=lambda: calls.append("reset"),
        )
        result = subject.recover(**args)
        self.assertEqual(calls, ["reset"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["failure"], "R2_RESET_DID_NOT_RESTORE_ZNP")
        self.assertEqual(result["verify_attempt"], 6)

    def test_dry_run_never_resets(self):
        calls = []
        args, _ = self.common(
            execute=False,
            reason=None,
            run_id=None,
            pre_probe=lambda: {"ok": False},
            reset_once=lambda: calls.append("reset"),
        )
        result = subject.recover(**args)
        self.assertEqual(calls, [])
        self.assertEqual(result["mode"], "preflight")
        self.assertFalse(result["reset_attempted"])

    def test_refuses_to_reset_healthy_p10(self):
        calls = []
        args, _ = self.common(
            pre_probe=lambda: {"ok": True, "revision": 20240716},
            reset_once=lambda: calls.append("reset"),
        )
        with self.assertRaisesRegex(RuntimeError, "already answers"):
            subject.recover(**args)
        self.assertEqual(calls, [])

    def test_wrong_mode_is_rejected_before_any_runtime_call(self):
        info = valid_info()
        info["coord_mode"] = 0
        calls = []
        args, _ = self.common(
            info=info,
            quiescent=lambda: calls.append("quiescent"),
            reset_once=lambda: calls.append("reset"),
        )
        with self.assertRaisesRegex(RuntimeError, "not in USB coordinator mode"):
            subject.recover(**args)
        self.assertEqual(calls, [])

    def test_wrong_radio_index_is_rejected(self):
        args, calls = self.common(expected_index=0)
        with self.assertRaisesRegex(RuntimeError, "radio index"):
            subject.recover(**args)
        self.assertEqual(calls, [])

    def test_ambiguous_p10_inventory_is_rejected(self):
        info = valid_info()
        info["radios"].append({
            "chip_index": 2,
            "zb_hw": "CC2674P10",
            "zb_version": 20240716,
            "zb_type": 0,
        })
        args, calls = self.common(info=info)
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            subject.recover(**args)
        self.assertEqual(calls, [])

    def test_wrong_firmware_revision_is_rejected(self):
        args, calls = self.common(expected_revision=20260311)
        with self.assertRaisesRegex(RuntimeError, "firmware revision"):
            subject.recover(**args)
        self.assertEqual(calls, [])

    def test_post_reset_revision_mismatch_fails_closed(self):
        calls = []
        args, _ = self.common(
            pre_probe=lambda: {"ok": False},
            post_probe=lambda: {"ok": True, "revision": 20260311},
            reset_once=lambda: calls.append("reset"),
        )
        with self.assertRaisesRegex(RuntimeError, "revision mismatch"):
            subject.recover(**args)
        self.assertEqual(calls, ["reset"])

    def test_private_host_policy(self):
        self.assertEqual(subject.private_ipv4("192.168.50.200"), "192.168.50.200")
        for bad in ("8.8.8.8", "127.0.0.1", "169.254.1.5"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    subject.private_ipv4(bad)

    def test_usb_endpoint_policy(self):
        good = (
            "/dev/serial/by-id/"
            "usb-SMLIGHT_SMLIGHT_SLZB-MR4U_SLZB-MR4U115162-if02"
        )
        self.assertEqual(subject.validate_usb_path(good), good)
        for bad in (
            "/dev/ttyACM1",
            good[:-2] + "00",
            "/dev/serial/by-id/usb-Other-if02",
            "/dev/serial/by-id/../../etc/passwd",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    subject.validate_usb_path(bad)


if __name__ == "__main__":
    unittest.main()
