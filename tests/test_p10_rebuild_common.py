from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import p10_rebuild_common as common


class FakeChannel:
    def settimeout(self, value):
        return None

    def recv_exit_status(self):
        return 1


class FakeStdout:
    def __init__(self):
        self.channel = FakeChannel()

    def read(self):
        return b""


class FakeClient:
    def __init__(self):
        self.commands = []

    def exec_command(self, command, timeout=None):
        self.commands.append(command)
        return None, FakeStdout(), None


class FakeSftpNoAtomic:
    def __init__(self):
        self.files = {"/x": b"old"}

    class Stat:
        st_mode = 0o100600

    def lstat(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.Stat()

    class Stream:
        def __init__(self, parent, path):
            self.parent = parent
            self.path = path
            self.buf = bytearray()

        def write(self, raw):
            self.buf.extend(raw)

        def flush(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.parent.files[self.path] = bytes(self.buf)

    def open(self, path, mode):
        return self.Stream(self, path)

    def chmod(self, path, mode):
        return None

    def posix_rename(self, src, dst):
        raise OSError("extension unavailable")

    def remove(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        del self.files[path]


class CommonStateMachineTests(TestCase):
    def test_startup_in_progress_does_not_issue_second_start(self):
        client = FakeClient()
        with (
            patch.object(common, "addon_info", return_value={"state": "startup"}),
            patch.object(common, "_wait_supervisor", return_value={"state": "started"}),
            patch.object(common, "_container_running", return_value=True),
        ):
            result = common.ensure_started(client)
        self.assertFalse(result["start_command_issued"])
        self.assertEqual(client.commands, [])

    def test_stop_command_exit_code_is_not_trusted_over_observed_state(self):
        client = FakeClient()
        with (
            patch.object(common, "addon_info", return_value={"state": "started"}),
            patch.object(common, "_wait_supervisor", return_value={"state": "stopped"}),
            patch.object(common, "_container_running", return_value=False),
        ):
            result = common.ensure_quiescent(client)
        self.assertTrue(result["addon_quiescent"])
        self.assertEqual(len(client.commands), 1)
        self.assertIn("apps stop", client.commands[0])

    def test_atomic_replace_refuses_remove_then_rename_fallback(self):
        sftp = FakeSftpNoAtomic()
        with self.assertRaisesRegex(RuntimeError, "Atomic POSIX rename"):
            common.atomic_replace(sftp, "/x", b"new")
        self.assertEqual(sftp.files["/x"], b"old")

    def test_network_fingerprint_excludes_network_key(self):
        base = {
            "coordinator_ieee": "00124b0011223344",
            "pan_id": "0x1234",
            "extended_pan_id": "0011223344556677",
            "channel": 11,
            "network_key": {"key": "00" * 16},
        }
        changed = dict(base)
        changed["network_key"] = {"key": "11" * 16}
        self.assertEqual(
            common.backup_network_fingerprint(base),
            common.backup_network_fingerprint(changed),
        )
