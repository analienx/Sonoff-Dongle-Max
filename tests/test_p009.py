from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
FIRMWARE = ROOT / "firmware"
if str(DEPLOY) not in sys.path:
    sys.path.insert(0, str(DEPLOY))
if str(FIRMWARE) not in sys.path:
    sys.path.insert(0, str(FIRMWARE))

from decode_ncp_counters import decode_line, summary
from p009_accept import parse_json_output, scan_hard_signatures, validate_active_result, validate_permit_result
from p009_common import (
    BUILDER_PIN,
    appended_logs,
    compare_identity,
    configure_remote,
    expected_addon_container,
    load_build_manifest,
    operational_identity_from_bridge_info,
    remote_argv,
    safe_identity_from_backup_doc,
)
from p009_deploy import (
    PHASE_ARMED,
    PHASE_FLASH,
    PHASE_IDENTITY,
    cmd_confirm_flash,
    parse_group_evidence,
    require_phase,
    runtime_readbacks,
    validate_session_target,
)
from verify_build import COMMON_PROFILE, P009_ONLY, STOCK_ONLY, linked_evidence, profile, validate_profile


def synthetic_slcp(rx_buffer: int, broadcast_table: int, key_table: int) -> str:
    entries = [
        ("SL_ZIGBEE_MULTICAST_TABLE_SIZE", 26, None),
        ("SL_ZIGBEE_NEIGHBOR_TABLE_SIZE", 26, None),
        ("SL_ZIGBEE_BINDING_TABLE_SIZE", 32, None),
        ("SL_ZIGBEE_BROADCAST_TABLE_SIZE", broadcast_table, None),
        ("SL_ZIGBEE_KEY_TABLE_SIZE", key_table, None),
        ("SL_ZIGBEE_DISCOVERY_TABLE_SIZE", 16, "xg24"),
        ("SL_ZIGBEE_ROUTE_TABLE_SIZE", 254, "xg24"),
        ("SL_ZIGBEE_SOURCE_ROUTE_TABLE_SIZE", 254, "xg24"),
        ("SL_ZIGBEE_ADDRESS_TABLE_SIZE", 128, "xg24"),
        ("SL_ZIGBEE_APS_UNICAST_MESSAGE_COUNT", 128, "xg24"),
        ("SL_ZIGBEE_MAX_END_DEVICE_CHILDREN", 64, "xg24"),
        ("SL_ZIGBEE_APS_DUPLICATE_REJECTION_MAX_ENTRIES", 64, "xg24"),
        ("SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE", "SL_ZIGBEE_HUGE_PACKET_BUFFER_HEAP", "xg24"),
    ]
    parts = []
    for name, value, condition in entries:
        parts.append(f"  - name: {name}\n    value: {value}")
        if condition == "xg24":
            parts.append('    condition: ["device_generic_family_efr32xg24"]')
    parts.append(f"  - name: SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE\n    value: {rx_buffer}\n    condition:\n      - iostream_eusart")
    return "\n".join(parts) + "\n"


def clean_active(successes: int = 16) -> dict[str, object]:
    return {
        "ok": successes >= 15,
        "expected": 16,
        "completed": 16,
        "unique_completed": 16,
        "scheduled": 16,
        "successes": successes,
        "global_timeout": False,
        "malformed_responses": 0,
    }


def clean_permit() -> dict[str, object]:
    return {
        "ok": True,
        "requested": {"all": 5, "coord": 0},
        "attempted": 5,
        "cleanup": {"ok": True, "fresh_permit_false": True},
        "final_permit": False,
        "hard_stop": None,
        "global_timeout": False,
        "malformed": [],
        "results": [{"ok": True} for _ in range(5)],
    }


def synthetic_build_manifest() -> dict[str, object]:
    p_profile = {**COMMON_PROFILE, **P009_ONLY, "SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE": "SL_ZIGBEE_HUGE_PACKET_BUFFER_HEAP"}
    s_profile = {**COMMON_PROFILE, **STOCK_ONLY, "SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE": "SL_ZIGBEE_HUGE_PACKET_BUFFER_HEAP"}
    return {
        "schema": 2,
        "source": {"repository": "analienx/Sonoff-Dongle-Max", "repository_commit": "a" * 40},
        "builder": {"repository": "Nerivec/silabs-firmware-builder", "commit": BUILDER_PIN},
        "firmware": {"emberznet": "9.1.1", "ezsp": 19},
        "p009": {"profile": p_profile, "artifacts": {"gbl": {"name": "p.gbl", "sha256": "1" * 64, "bytes": 100}}},
        "rollback_stock": {"profile": s_profile, "artifacts": {"gbl": {"name": "s.gbl", "sha256": "2" * 64, "bytes": 100}}},
        "allowed_profile_differences": sorted(P009_ONLY),
        "linked_evidence": {"validated": True, "bss_delta_bytes": 704, "memory_manager_heap_delta_bytes": 0},
    }


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

    def test_expected_addon_container_is_exact(self):
        self.assertEqual(expected_addon_container("45df7312_zigbee2mqtt"), "addon_45df7312_zigbee2mqtt")
        self.assertEqual(expected_addon_container("addon_45df7312_zigbee2mqtt"), "addon_45df7312_zigbee2mqtt")

    def test_bridge_info_operational_identity_uses_live_network_fields(self):
        info = {
            "coordinator": {"ieee_address": "0x00124b0000000001", "type": "EmberZNet"},
            "network": {"pan_id": 0x1234, "extended_pan_id": "0x0011223344556677", "channel": 11},
        }
        self.assertEqual(
            operational_identity_from_bridge_info(info),
            {
                "coordinator_ieee": "0x00124b0000000001",
                "pan_id": 0x1234,
                "extended_pan_id": "0x0011223344556677",
                "channel": 11,
            },
        )

    def test_bridge_info_operational_identity_rejects_missing_fields(self):
        with self.assertRaises(SystemExit):
            operational_identity_from_bridge_info({"coordinator": {"ieee_address": "aa"}, "network": {"channel": 11}})

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

    def test_runtime_readback_rejects_mismatch_with_normal_exception(self):
        with self.assertRaises(RuntimeError):
            runtime_readbacks(["[P009 EZSP] BROADCAST_TABLE_SIZE expected=64 actual=30 readStatus=OK"])

    def test_acceptance_bad_json_uses_normal_exception(self):
        with self.assertRaises(RuntimeError):
            parse_json_output("not-json", "canary")

    def test_active_accepts_complete_15_of_16(self):
        validate_active_result(clean_active(15))

    def test_active_rejects_incomplete_15_of_15_even_if_marked_ok(self):
        rec = clean_active(15)
        rec.update({"completed": 15, "unique_completed": 15, "scheduled": 15, "ok": True})
        with self.assertRaises(RuntimeError):
            validate_active_result(rec)

    def test_active_rejects_global_timeout_and_malformed(self):
        rec = clean_active()
        rec["global_timeout"] = True
        with self.assertRaises(RuntimeError):
            validate_active_result(rec)
        rec = clean_active()
        rec["malformed_responses"] = 1
        with self.assertRaises(RuntimeError):
            validate_active_result(rec)

    def test_permit_accepts_exact_clean_five_with_fresh_cleanup(self):
        validate_permit_result(clean_permit())

    def test_permit_rejects_fail_fast_partial_as_success(self):
        rec = clean_permit()
        rec.update({"attempted": 2, "ok": False, "hard_stop": "first failed trial all#2"})
        with self.assertRaises(RuntimeError):
            validate_permit_result(rec)

    def test_permit_rejects_stale_or_failed_cleanup(self):
        rec = clean_permit()
        rec["cleanup"] = {"ok": False, "fresh_permit_false": False}
        with self.assertRaises(RuntimeError):
            validate_permit_result(rec)

    def test_hard_signature_scan_catches_pressure_and_fatal_events(self):
        text = "normal line\nstatus=BUSY\nNO_BUFFERS\nzh:ember ASH reset\nNETWORK_DOWN\n"
        got = scan_hard_signatures(text)
        self.assertEqual(len(got), 4)
        self.assertEqual(scan_hard_signatures("normal route update\nall good\n"), [])

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

    def test_session_target_lock(self):
        session = {"host": "ha", "addon": "z2m", "z2m_dir": "/config/zigbee2mqtt", "remote_template": "rtk proxy ssh {host} {command}"}
        args = SimpleNamespace(host="ha", addon="z2m", z2m_dir="/config/zigbee2mqtt", remote_template="rtk proxy ssh {host} {command}")
        validate_session_target(session, args)
        args.host = "other"
        with self.assertRaises(SystemExit):
            validate_session_target(session, args)

    def test_manual_flash_gate_requires_exact_armed_hash(self):
        digest = "ab" * 32
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.json"
            path.write_text(json.dumps({
                "phase": PHASE_ARMED,
                "host": "ha",
                "addon": "z2m",
                "z2m_dir": "/config/zigbee2mqtt",
                "remote_template": "ssh {host} {command}",
                "p009_gbl": {"sha256": digest},
            }), encoding="utf-8")
            args = SimpleNamespace(
                confirm="P009-FLASHED", session=path, observed_sha256=digest,
                webui_note="success", host="ha", addon="z2m", z2m_dir="/config/zigbee2mqtt",
                remote_template="ssh {host} {command}",
            )
            cmd_confirm_flash(args)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["phase"], PHASE_FLASH)
            self.assertIn("not device-side", saved["manual_flash"]["proof_scope"])

    def test_group_evidence_requires_structured_fields(self):
        good = json.dumps({
            "group": "Lights All",
            "command": "OFF",
            "timestamp": "2026-09-07T21:00:00+02:00",
            "command_result": "Z2M accepted",
            "physical_result": "all selected loads off",
        })
        self.assertEqual(parse_group_evidence(good)["group"], "Lights All")
        with self.assertRaises(SystemExit):
            parse_group_evidence(json.dumps({"group": "x", "command": "OFF"}))

    def test_hardened_manifest_accepts_rx512_and_linked_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manifest.json"
            path.write_text(json.dumps(synthetic_build_manifest()), encoding="utf-8")
            got = load_build_manifest(path)
            self.assertEqual(got["p009"]["profile"]["SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE"], 512)

    def test_hardened_manifest_rejects_missing_rx512_or_linked_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manifest.json"
            doc = synthetic_build_manifest()
            doc["p009"]["profile"]["SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE"] = 128
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_build_manifest(path)
            doc = synthetic_build_manifest()
            doc["linked_evidence"]["validated"] = False
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_build_manifest(path)

    def test_verify_build_profile_extraction_matches_p009_delta(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "p009.slcp"
            path.write_text(synthetic_slcp(rx_buffer=512, broadcast_table=64, key_table=12), encoding="utf-8")
            got = profile(path)
        validate_profile(got, P009_ONLY)
        self.assertEqual(got["SL_ZIGBEE_BROADCAST_TABLE_SIZE"], 64)
        self.assertEqual(got["SL_ZIGBEE_KEY_TABLE_SIZE"], 12)
        self.assertEqual(got["SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE"], 512)
        self.assertEqual(got["SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE"], "SL_ZIGBEE_HUGE_PACKET_BUFFER_HEAP")
        for name, value in COMMON_PROFILE.items():
            self.assertEqual(got[name], value)

    def test_verify_build_profile_extraction_matches_stock_delta(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stock.slcp"
            path.write_text(synthetic_slcp(rx_buffer=128, broadcast_table=30, key_table=1), encoding="utf-8")
            got = profile(path)
        validate_profile(got, STOCK_ONLY)

    def test_verify_build_profile_rejects_wrong_delta(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.slcp"
            path.write_text(synthetic_slcp(rx_buffer=128, broadcast_table=64, key_table=1), encoding="utf-8")
            got = profile(path)
        with self.assertRaises(SystemExit):
            validate_profile(got, STOCK_ONLY)

    def test_linked_elf_contract_checks_sections_symbols_and_704_delta(self):
        sizes = {
            "stock": {
                "rx_buffer_vcom": 128,
                "sli_zigbee_broadcast_table_data": 240,
                "sli_zigbee_incoming_aps_frame_counters": 8,
                "sli_zigbee_retry_queue": 320,
                "sli_zigbee_multicast_table": 104,
                "sli_zigbee_source_route_table_data": 1016,
                "sli_zigbee_route_table": 2040,
                "sli_zigbee_child_table_data": 1560,
            },
            "p009": {
                "rx_buffer_vcom": 512,
                "sli_zigbee_broadcast_table_data": 512,
                "sli_zigbee_incoming_aps_frame_counters": 52,
                "sli_zigbee_retry_queue": 320,
                "sli_zigbee_multicast_table": 104,
                "sli_zigbee_source_route_table_data": 1016,
                "sli_zigbee_route_table": 2040,
                "sli_zigbee_child_table_data": 1560,
            },
        }

        def fake_readelf(path: Path, flag: str) -> str:
            variant = "stock" if "stock" in path.name else "p009"
            if flag == "-SW":
                bss = "00570c" if variant == "stock" else "0059cc"
                return (
                    f"  [ 1] .bss NOBITS 20001008 001008 {bss} 00 WA 0 0 8\n"
                    "  [ 2] .memory_manager_heap NOBITS 20007df8 000000 038208 00 WA 0 0 8\n"
                )
            return "".join(
                f"   {i}: 20000000 {size} OBJECT GLOBAL DEFAULT 5 {name}\n"
                for i, (name, size) in enumerate(sizes[variant].items(), 1)
            )

        with patch("verify_build._readelf", side_effect=fake_readelf):
            report = linked_evidence(Path("stock.out"), Path("p009.out"))
        self.assertTrue(report["validated"])
        self.assertEqual(report["bss_delta_bytes"], 704)
        self.assertEqual(report["symbols"]["p009"]["rx_buffer_vcom"], 512)

    def test_ncp_counter_decoder_extracts_pressure_signals(self):
        values = [0] * 42
        values[18] = 1
        values[27] = 2
        values[31] = 3
        values[32] = 4
        values[33] = 5
        values[40] = 6
        line = "2026-09-04 10:11:12 info: zh:ember: [NCP COUNTERS] " + ",".join(map(str, values))
        rec = decode_line(line, source="test.log", line_number=7)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["timestamp"], "2026-09-04 10:11:12")
        self.assertEqual(rec["selected"]["BROADCAST_TABLE_FULL"], 5)
        self.assertEqual(rec["selected"]["NWK_RETRY_OVERFLOW"], 3)
        self.assertEqual(rec["nonzero_pressure"]["ADDRESS_CONFLICT_SENT"], 6)

    def test_ncp_counter_summary_aggregates_intervals(self):
        records = []
        for btt in (0, 2, 3):
            values = [0] * 42
            values[33] = btt
            rec = decode_line("[NCP COUNTERS] " + ",".join(map(str, values)), source="x", line_number=1)
            assert rec is not None
            records.append(rec)
        report = summary(records)
        self.assertEqual(report["intervals"], 3)
        self.assertEqual(report["totals"]["BROADCAST_TABLE_FULL"], 5)
        self.assertEqual(report["max_per_interval"]["BROADCAST_TABLE_FULL"], 3)
        self.assertEqual(report["nonzero_intervals"]["BROADCAST_TABLE_FULL"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
