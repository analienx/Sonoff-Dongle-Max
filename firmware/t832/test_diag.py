from __future__ import annotations

import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("t832_incident", HERE / "t832_incident.py")
assert SPEC and SPEC.loader
incident = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(incident)


def packet_hex(
    *,
    export_sequence: int = 1,
    uptime_ms: int = 12345,
    event_kind: int = 19,
    a: int = 7,
    b: int = 8,
    c: int = 9,
) -> str:
    header = struct.pack(
        "<4sBBHHQIIHHH",
        b"T8D1",
        1,
        1,
        export_sequence,
        1,
        uptime_ms,
        8320001,
        0x1FFF,
        0,
        0,
        0,
    )
    record = struct.pack(
        "<IIHBBHHHH",
        100,
        101,
        export_sequence,
        event_kind,
        0,
        a,
        b,
        c,
        1,
    )
    return (header + record).hex().upper()


class DecodeTests(unittest.TestCase):
    def test_packet_round_trip(self) -> None:
        decoded = incident.decode_packet(packet_hex(event_kind=24, a=1, b=9))
        self.assertEqual(decoded["signature"], "T8D1")
        self.assertEqual(decoded["record"]["kind_name"], "NETWORK_STATE")
        self.assertEqual(decoded["record"]["a"], 1)
        self.assertEqual(decoded["record"]["b"], 9)

    def test_bad_packet_rejected(self) -> None:
        with self.assertRaises(ValueError):
            incident.decode_packet("00")


class CollectorTests(unittest.TestCase):
    def test_file_only_collection_and_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = incident.Store(root / "private")
            log = root / "z2m.log"
            log.write_text(
                "2026-10-03T09:00:00Z zh:zstack:znp DEBUG.msg "
                f"T832D1:{packet_hex(export_sequence=1, uptime_ms=1000)}\n"
                "2026-10-03T09:00:05Z serial timeout "
                f"T832D1:{packet_hex(export_sequence=3, uptime_ms=6000)}\n",
                encoding="utf-8",
            )
            result = incident.collect(
                store,
                [str(log)],
                config_fingerprint="cfg",
                initial_tail_bytes=1024 * 1024,
                retain_days=7,
                max_bytes=1 << 30,
            )
            self.assertEqual(result["diag_records"], 2)
            day = incident.utcnow().strftime("%Y-%m-%d")
            rows = [
                json.loads(line)
                for line in (store.stream / f"diag-{day}.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(rows[0]["sequence_gap_before"], 0)
            self.assertEqual(rows[1]["sequence_gap_before"], 1)
            self.assertEqual(rows[1]["config_fingerprint"], "cfg")
            self.assertTrue((store.stream / f"host-{day}.jsonl").exists())

    def test_missing_source_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = incident.Store(Path(td) / "private")
            result = incident.collect(
                store,
                [str(Path(td) / "missing.log")],
                config_fingerprint=None,
                initial_tail_bytes=1024,
                retain_days=7,
                max_bytes=1 << 20,
            )
            self.assertEqual(result["sources_seen"], 0)
            self.assertTrue(result["missing_sources"])


class IncidentTests(unittest.TestCase):
    def test_capture_and_one_reset_latch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = incident.Store(root / "private")
            log = root / "z2m.log"
            log.write_text(
                "2026-10-03T09:00:00Z zh:zstack:znp "
                f"T832D1:{packet_hex(event_kind=13)}\n",
                encoding="utf-8",
            )
            captured = incident.capture(
                store,
                "unit-test",
                sources=[str(log)],
                config_fingerprint="cfg",
                initial_tail_bytes=1024 * 1024,
                retain_days=7,
                max_bytes=1 << 30,
                window_seconds=15 * 60,
                deadline_seconds=30,
            )
            self.assertEqual(captured["status"], "captured")
            bundle = Path(captured["bundle"])
            self.assertTrue((bundle / "manifest.json").exists())
            self.assertTrue((bundle / "SHA256.json").exists())

            authorized = incident.authorize_reset(store)
            self.assertTrue(authorized["reset_used"])
            with self.assertRaises(RuntimeError):
                incident.authorize_reset(store)

            # A fresh Store instance sees the same persistent latch.
            store2 = incident.Store(root / "private")
            status = store2.load(store2.latch, {})
            self.assertEqual(status["status"], "reset_authorized")

    def test_failed_recovery_stays_latched(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = incident.Store(Path(td) / "private")
            store.atomic_json(
                store.latch,
                {
                    "status": "reset_authorized",
                    "incident_id": "x",
                    "reset_used": True,
                },
            )
            failed = incident.recovery_result(store, success=False, normal_traffic=False)
            self.assertEqual(failed["status"], "failed")
            with self.assertRaises(RuntimeError):
                incident.authorize_reset(store)

    def test_close_requires_stability_window_and_traffic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = incident.Store(Path(td) / "private")
            store.atomic_json(
                store.latch,
                {
                    "status": "stabilizing",
                    "incident_id": "x",
                    "reset_used": True,
                    "normal_traffic_observed": True,
                    "stable_after_utc": "2000-01-01T00:00:00Z",
                },
            )
            closed = incident.close_if_stable(store, bridge_up=True, normal_traffic=True)
            self.assertEqual(closed["status"], "closed")


class ProtocolEdgeTests(unittest.TestCase):
    def test_malformed_and_unknown_schema_rejected(self) -> None:
        with self.assertRaises(ValueError):
            incident.decode_packet("00" * 10)
        bad_magic = bytearray(bytes.fromhex(packet_hex()))
        bad_magic[0:4] = b"BAD!"
        with self.assertRaises(ValueError):
            incident.decode_packet(bytes(bad_magic).hex().upper())
        bad_schema = bytearray(bytes.fromhex(packet_hex()))
        bad_schema[4] = 99
        with self.assertRaises(ValueError):
            incident.decode_packet(bytes(bad_schema).hex().upper())

    def test_sequence_rollover_and_restart_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = incident.Store(root / "private")
            log = root / "z2m.log"
            log.write_text(
                "2026-10-03T09:00:00Z zh:zstack:znp "
                f"T832D1:{packet_hex(export_sequence=65534, uptime_ms=1000)}\n"
                "2026-10-03T09:00:01Z zh:zstack:znp "
                f"T832D1:{packet_hex(export_sequence=2, uptime_ms=500)}\n",
                encoding="utf-8",
            )
            result = incident.collect(
                store,
                [str(log)],
                config_fingerprint=None,
                initial_tail_bytes=1024 * 1024,
                retain_days=7,
                max_bytes=1 << 30,
            )
            self.assertEqual(result["diag_records"], 2)
            day = incident.utcnow().strftime("%Y-%m-%d")
            rows = [
                json.loads(line)
                for line in (store.stream / f"diag-{day}.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(rows[1]["session_reset_detected"])
            self.assertEqual(rows[1]["sequence_gap_before"], 0)

    def test_dropped_sequence_reports_gap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = incident.Store(root / "private")
            log = root / "z2m.log"
            log.write_text(
                "2026-10-03T09:00:00Z zh:zstack:znp "
                f"T832D1:{packet_hex(export_sequence=10, uptime_ms=1000)}\n"
                "2026-10-03T09:00:05Z zh:zstack:znp "
                f"T832D1:{packet_hex(export_sequence=14, uptime_ms=6000)}\n",
                encoding="utf-8",
            )
            incident.collect(
                store,
                [str(log)],
                config_fingerprint=None,
                initial_tail_bytes=1024 * 1024,
                retain_days=7,
                max_bytes=1 << 30,
            )
            day = incident.utcnow().strftime("%Y-%m-%d")
            rows = [
                json.loads(line)
                for line in (store.stream / f"diag-{day}.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(rows[1]["sequence_gap_before"], 3)

    def test_corrupt_record_yields_decode_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = incident.Store(root / "private")
            log = root / "z2m.log"
            log.write_text(
                "2026-10-03T09:00:00Z zh:zstack:znp T832D1:" + "00" * 52 + "\n",
                encoding="utf-8",
            )
            result = incident.collect(
                store,
                [str(log)],
                config_fingerprint=None,
                initial_tail_bytes=1024,
                retain_days=7,
                max_bytes=1 << 20,
            )
            self.assertEqual(result["diag_records"], 1)
            day = incident.utcnow().strftime("%Y-%m-%d")
            row = json.loads((store.stream / f"diag-{day}.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["type"], "decode_error")

    def test_startup_breadcrumb_kinds_decode(self) -> None:
        for kind, name in ((13, "STARTUP_FROM_APP_ENTRY"), (14, "STARTUP_BDB_REQUEST"), (15, "STARTUP_BDB_RETURN"), (16, "STARTUP_SRSP_QUEUE")):
            decoded = incident.decode_packet(packet_hex(event_kind=kind))
            self.assertEqual(decoded["record"]["kind_name"], name)

    def test_gap_closure_kinds_decode(self) -> None:
        for kind, name in ((26, "TASK_EVENTS"), (27, "NV_EVENT"), (28, "AF_STATE"), (29, "NV_FAULT")):
            decoded = incident.decode_packet(packet_hex(event_kind=kind))
            self.assertEqual(decoded["record"]["kind_name"], name)

    def test_rotation_cap_and_collector_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = incident.Store(root / "private")
            log = root / "z2m.log"
            log.write_text(
                "2026-10-03T09:00:00Z zh:zstack:znp "
                f"T832D1:{packet_hex(export_sequence=1, uptime_ms=1000)}\n",
                encoding="utf-8",
            )
            first = incident.collect(
                store, [str(log)], config_fingerprint=None,
                initial_tail_bytes=1024 * 1024, retain_days=7, max_bytes=1 << 30,
            )
            self.assertEqual(first["diag_records"], 1)
            store2 = incident.Store(root / "private")
            second = incident.collect(
                store2, [str(log)], config_fingerprint=None,
                initial_tail_bytes=1024 * 1024, retain_days=7, max_bytes=1 << 30,
            )
            self.assertEqual(second["diag_records"], 0)
            incident.rotate(store, retain_days=7, max_bytes=1)
            remaining = list(store.stream.glob("*.jsonl"))
            self.assertEqual(remaining, [])


class RecoveryEdgeTests(unittest.TestCase):
    def test_repeated_trigger_while_latched_refused(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = incident.Store(Path(td) / "private")
            log = Path(td) / "z2m.log"
            log.write_text("2026-10-03T09:00:00Z boot\n", encoding="utf-8")
            incident.capture(
                store, "first", sources=[str(log)], config_fingerprint=None,
                initial_tail_bytes=1024, retain_days=7, max_bytes=1 << 20,
                window_seconds=900, deadline_seconds=30,
            )
            with self.assertRaises(RuntimeError):
                incident.capture(
                    store, "second", sources=[str(log)], config_fingerprint=None,
                    initial_tail_bytes=1024, retain_days=7, max_bytes=1 << 20,
                    window_seconds=900, deadline_seconds=30,
                )

    def test_partial_sys_only_recovery_stays_failed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = incident.Store(Path(td) / "private")
            store.atomic_json(store.latch, {"status": "recovering", "incident_id": "x", "reset_used": True})
            result = store.load(store.latch, {})
            self.assertEqual(result["status"], "recovering")
            failed = incident.recovery_result(store, success=True, normal_traffic=False)
            self.assertEqual(failed["status"], "failed")
            with self.assertRaises(RuntimeError):
                incident.authorize_reset(store)

    def test_host_event_correlation_without_serial(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = incident.Store(root / "private")
            log = root / "z2m.log"
            log.write_text(
                "2026-10-03T09:00:00Z serial port RTS asserted, zigbee2mqtt bridge offline\n",
                encoding="utf-8",
            )
            result = incident.collect(
                store, [str(log)], config_fingerprint=None,
                initial_tail_bytes=1024 * 1024, retain_days=7, max_bytes=1 << 30,
            )
            self.assertEqual(result["host_events"], 1)


if __name__ == "__main__":
    unittest.main()
