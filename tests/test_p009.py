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
for p in (ROOT / "deploy", ROOT / "firmware"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from decode_ncp_counters import decode_line, summary
from p009_accept import parse_json_output, scan_hard_signatures, validate_active_result, validate_permit_result
from p009_common import (
    BUILDER_PIN,
    addon_container_candidates,
    addon_state,
    appended_logs,
    compare_identity,
    configure_remote,
    find_gbl,
    normalize_addon_info,
    operational_identity_from_bridge_info,
    require_single_z2m_owner,
    remote_argv,
    safe_identity_from_backup_doc,
)
from p009_deploy import PHASE_ARMED, PHASE_FLASH, PHASE_IDENTITY, cmd_confirm_flash, parse_group_evidence, require_phase, runtime_readbacks, validate_session_target
from p009_version import load_build_manifest_approved
from verify_build import COMMON_PROFILE, P009_ONLY, STOCK_ONLY, linked_evidence, profile, validate_profile


def synthetic_slcp(rx: int, btt: int, key: int, mcast: int = 26) -> str:
    entries = [
        ("SL_ZIGBEE_MULTICAST_TABLE_SIZE", mcast, None),
        ("SL_ZIGBEE_NEIGHBOR_TABLE_SIZE", 26, None),
        ("SL_ZIGBEE_BINDING_TABLE_SIZE", 32, None),
        ("SL_ZIGBEE_BROADCAST_TABLE_SIZE", btt, None),
        ("SL_ZIGBEE_KEY_TABLE_SIZE", key, None),
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
    for name, value, cond in entries:
        parts.append(f"  - name: {name}\n    value: {value}")
        if cond:
            parts.append('    condition: ["device_generic_family_efr32xg24"]')
    parts.append(f"  - name: SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE\n    value: {rx}\n    condition:\n      - iostream_eusart")
    return "\n".join(parts) + "\n"


def clean_active(successes: int = 16) -> dict[str, object]:
    return {"ok": successes >= 15, "expected": 16, "completed": 16, "unique_completed": 16, "scheduled": 16, "successes": successes, "global_timeout": False, "malformed_responses": 0}


def clean_permit() -> dict[str, object]:
    return {"ok": True, "requested": {"all": 5, "coord": 0}, "attempted": 5, "cleanup": {"ok": True, "fresh_permit_false": True}, "final_permit": False, "hard_stop": None, "global_timeout": False, "malformed": [], "results": [{"ok": True} for _ in range(5)]}


def synthetic_manifest() -> dict[str, object]:
    p = {**COMMON_PROFILE, **P009_ONLY, "SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE": "SL_ZIGBEE_HUGE_PACKET_BUFFER_HEAP"}
    s = {**COMMON_PROFILE, **STOCK_ONLY, "SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE": "SL_ZIGBEE_HUGE_PACKET_BUFFER_HEAP"}
    return {
        "schema": 2,
        "profile_id": "P009-RX512-BTT64-KEY12-MCAST26",
        "source": {"repository": "analienx/Sonoff-Dongle-Max", "repository_commit": "a" * 40},
        "builder": {"repository": "Nerivec/silabs-firmware-builder", "commit": BUILDER_PIN},
        "firmware": {"emberznet": "9.1.1", "ezsp": 19},
        "p009": {"profile": p, "artifacts": {"gbl": {"name": "p.gbl", "sha256": "1" * 64, "bytes": 100}}},
        "rollback_stock": {"profile": s, "artifacts": {"gbl": {"name": "s.gbl", "sha256": "2" * 64, "bytes": 100}}},
        "allowed_profile_differences": sorted(P009_ONLY),
        "linked_evidence": {"validated": True, "bss_delta_bytes": 704, "memory_manager_heap_delta_bytes": 0},
    }


class P009Tests(unittest.TestCase):
    def test_safe_identity_never_returns_plain_network_key(self):
        key = "00112233445566778899aabbccddeeff"
        doc = {"metadata": {"format": "zigpy/open-coordinator-backup", "source": "test", "internal": {"ezspVersion": 19}}, "coordinator_ieee": "fdb1122d004b1200", "pan_id": "45a1", "extended_pan_id": "d6167914c10a3a3a", "channel": 11, "network_key": {"key": key, "sequence_number": 0}, "devices": [{"ieee_address": "00124b0000000001"}]}
        identity = safe_identity_from_backup_doc(doc)
        self.assertEqual(identity["network_key_sha256"], hashlib.sha256(bytes.fromhex(key)).hexdigest())
        self.assertNotIn(key, json.dumps(identity))

    def test_remote_templates_and_exact_addon_owner_name(self):
        configure_remote("ssh {host} {command}")
        self.assertEqual(remote_argv("ha", "echo ok"), ["ssh", "ha", "echo ok"])
        configure_remote("rtk proxy ssh {host} {command}")
        self.assertEqual(remote_argv("ha", "echo ok"), ["rtk", "proxy", "ssh", "ha", "echo ok"])
        slug = "45df7312_zigbee2mqtt"
        self.assertIn(f"app_{slug}", addon_container_candidates(slug, {"slug": slug}))
        self.assertIn(f"addon_{slug}", addon_container_candidates(slug, {"slug": slug}))
        with patch("p009_common.running_z2m_containers", return_value=[f"app_{slug}"]), patch("p009_common.addon_info", return_value={"slug": slug}):
            self.assertEqual(require_single_z2m_owner("ha", slug), f"app_{slug}")
        with patch("p009_common.running_z2m_containers", return_value=[f"rogue_{slug}"]), patch("p009_common.addon_info", return_value={"slug": slug}), patch("p009_common.remote_exec", return_value="{}"):
            with self.assertRaises(SystemExit):
                require_single_z2m_owner("ha", slug)
        envelope = {"result": "ok", "data": {"state": "started", "version": "2.14.0-1", "slug": slug}}
        self.assertEqual(addon_state(normalize_addon_info(envelope)), "started")
        with self.assertRaises(SystemExit):
            configure_remote("ssh ha")

    def test_live_bridge_identity_requires_all_network_fields(self):
        info = {"coordinator": {"ieee_address": "0x00124b0000000001", "type": "EmberZNet"}, "network": {"pan_id": 0x1234, "extended_pan_id": "0x0011223344556677", "channel": 11}}
        self.assertEqual(operational_identity_from_bridge_info(info)["channel"], 11)
        with self.assertRaises(SystemExit):
            operational_identity_from_bridge_info({"coordinator": {"ieee_address": "aa"}, "network": {"channel": 11}})

    def test_log_suffix_detects_rotation(self):
        delta, exact = appended_logs("a\nb\n", "a\nb\nc\nd\n")
        self.assertTrue(exact)
        self.assertEqual(delta, "c\nd\n")
        delta, exact = appended_logs("old\n", "\n".join(f"line-{i}" for i in range(700)))
        self.assertFalse(exact)
        self.assertEqual(len(delta.splitlines()), 500)

    def test_runtime_policy_readback_is_exact(self):
        values = {"BROADCAST_TABLE_SIZE": 64, "NEW_BROADCAST_ENTRY_THRESHOLD": 48, "RETRY_QUEUE_SIZE": 16, "MTORR_FLOW_CONTROL": 1, "SUPPORTED_NETWORKS": 1, "SEND_MULTICASTS_TO_SLEEPY_ADDRESS": 0}
        lines = [f"[P009 EZSP] {k} expected={v} actual={v} readStatus=OK" for k, v in values.items()]
        self.assertEqual(set(runtime_readbacks(lines)), set(values))
        with self.assertRaises(RuntimeError):
            runtime_readbacks(["[P009 EZSP] BROADCAST_TABLE_SIZE expected=64 actual=30 readStatus=OK"])

    def test_active_acceptance_requires_all_16_completed(self):
        validate_active_result(clean_active(15))
        rec = clean_active(15)
        rec.update({"completed": 15, "unique_completed": 15, "scheduled": 15, "ok": True})
        with self.assertRaises(RuntimeError):
            validate_active_result(rec)
        rec = clean_active()
        rec["malformed_responses"] = 1
        with self.assertRaises(RuntimeError):
            validate_active_result(rec)
        rec = clean_active(); rec["hard_events"] = [{"message": "NETWORK_DOWN"}]
        with self.assertRaises(RuntimeError):
            validate_active_result(rec)
        with self.assertRaises(RuntimeError):
            parse_json_output("not-json", "canary")

    def test_permit_join_is_fail_fast_and_cleanup_bound(self):
        validate_permit_result(clean_permit())
        rec = clean_permit(); rec.update({"attempted": 2, "ok": False, "hard_stop": "first failed trial all#2"})
        with self.assertRaises(RuntimeError):
            validate_permit_result(rec)
        rec = clean_permit(); rec["cleanup"] = {"ok": False, "fresh_permit_false": False}
        with self.assertRaises(RuntimeError):
            validate_permit_result(rec)

    def test_hard_signature_scan(self):
        got = scan_hard_signatures("normal\nstatus=BUSY\nNO_BUFFERS\nzh:ember ASH reset\nNETWORK_DOWN\n")
        self.assertEqual(len(got), 4)
        self.assertEqual(scan_hard_signatures("normal route update\nall good\n"), [])

    def test_network_identity_drift_is_rejected(self):
        base = {"identity": {"coordinator_ieee": "aa", "pan_id": "bb", "extended_pan_id": "cc", "channel": 11, "network_key_sha256": "dd", "network_key_sequence_number": 0, "device_backup_entries": 104}}
        same = json.loads(json.dumps(base))
        self.assertEqual(compare_identity(base, same), [])
        changed = json.loads(json.dumps(base)); changed["identity"]["channel"] = 15
        self.assertIn("channel", compare_identity(base, changed)[0])

    def test_state_and_target_gates(self):
        require_phase({"phase": PHASE_ARMED}, PHASE_ARMED)
        with self.assertRaises(SystemExit):
            require_phase({"phase": PHASE_ARMED}, PHASE_IDENTITY)
        session = {"host": "ha", "addon": "z2m", "z2m_dir": "/config/zigbee2mqtt", "remote_template": "rtk proxy ssh {host} {command}"}
        args = SimpleNamespace(host="ha", addon="z2m", z2m_dir="/config/zigbee2mqtt", remote_template="rtk proxy ssh {host} {command}")
        validate_session_target(session, args)
        args.host = "other"
        with self.assertRaises(SystemExit):
            validate_session_target(session, args)

    def test_manual_flash_ack_is_bound_to_armed_hash(self):
        digest = "ab" * 32
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.json"
            path.write_text(json.dumps({"phase": PHASE_ARMED, "host": "ha", "addon": "z2m", "z2m_dir": "/config/zigbee2mqtt", "remote_template": "ssh {host} {command}", "p009_gbl": {"sha256": digest}}), encoding="utf-8")
            args = SimpleNamespace(confirm="P009-FLASHED", session=path, observed_sha256=digest, webui_note="success", host="ha", addon="z2m", z2m_dir="/config/zigbee2mqtt", remote_template="ssh {host} {command}")
            cmd_confirm_flash(args)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["phase"], PHASE_FLASH)
            self.assertIn("not device-side", saved["manual_flash"]["proof_scope"])

    def test_group_evidence_is_structured(self):
        good = json.dumps({"group": "Lights All", "command": "OFF", "timestamp": "2026-09-08T20:00:00+02:00", "command_result": "PASS", "physical_result": "PASS", "physical_observation": "selected loads visibly switched off"})
        self.assertEqual(parse_group_evidence(good)["group"], "Lights All")
        bad = json.dumps({"group": "Lights All", "command": "OFF", "timestamp": "2026-09-08T20:00:00+02:00", "command_result": "failed", "physical_result": "not performed", "physical_observation": "none"})
        with self.assertRaises(SystemExit):
            parse_group_evidence(bad)
        with self.assertRaises(SystemExit):
            parse_group_evidence(json.dumps({"group": "x", "command": "OFF"}))

    def test_release_rollback_directory_is_stock_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "stock-rollback" / "stock.gbl"
            target.parent.mkdir()
            target.write_bytes(b"gbl")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            manifest = {"rollback_stock": {"artifacts": {"gbl": {"name": "stock.gbl", "sha256": digest, "bytes": 3}}}}
            self.assertEqual(find_gbl(root, manifest, "stock"), target)

    def test_deployment_manifest_accepts_only_frozen_p009(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manifest.json"
            path.write_text(json.dumps(synthetic_manifest()), encoding="utf-8")
            got = load_build_manifest_approved(path)
            self.assertEqual(got["p009"]["profile"]["SL_ZIGBEE_MULTICAST_TABLE_SIZE"], 26)
            bad = synthetic_manifest(); bad["p009"]["profile"]["SL_ZIGBEE_MULTICAST_TABLE_SIZE"] = 32
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_build_manifest_approved(path)
            bad = synthetic_manifest(); bad["linked_evidence"]["bss_delta_bytes"] = 728
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_build_manifest_approved(path)

    def test_source_profiles_are_exact(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "p009.slcp"; p.write_text(synthetic_slcp(512, 64, 12, 26), encoding="utf-8")
            s = Path(td) / "stock.slcp"; s.write_text(synthetic_slcp(128, 30, 1, 26), encoding="utf-8")
            pg, sg = profile(p), profile(s)
        validate_profile(pg, P009_ONLY); validate_profile(sg, STOCK_ONLY)
        self.assertEqual(pg["SL_ZIGBEE_MULTICAST_TABLE_SIZE"], 26)
        self.assertEqual(pg["SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE"], 512)
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.slcp"; bad.write_text(synthetic_slcp(512, 64, 12, 32), encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_profile(profile(bad), P009_ONLY)

    def test_linked_elf_contract_is_704_bytes_and_mcast_unchanged(self):
        sizes = {
            "stock": {"rx_buffer_vcom": 128, "sli_zigbee_broadcast_table_data": 240, "sli_zigbee_incoming_aps_frame_counters": 8, "sli_zigbee_retry_queue": 320, "sli_zigbee_multicast_table": 104, "sli_zigbee_source_route_table_data": 1016, "sli_zigbee_route_table": 2040, "sli_zigbee_child_table_data": 1560},
            "p009": {"rx_buffer_vcom": 512, "sli_zigbee_broadcast_table_data": 512, "sli_zigbee_incoming_aps_frame_counters": 52, "sli_zigbee_retry_queue": 320, "sli_zigbee_multicast_table": 104, "sli_zigbee_source_route_table_data": 1016, "sli_zigbee_route_table": 2040, "sli_zigbee_child_table_data": 1560},
        }
        def fake_readelf(path: Path, flag: str) -> str:
            variant = "stock" if "stock" in path.name else "p009"
            if flag == "-SW":
                bss = "00570c" if variant == "stock" else "0059cc"
                return f"  [ 1] .bss NOBITS 20001008 001008 {bss} 00 WA 0 0 8\n  [ 2] .memory_manager_heap NOBITS 20007df8 000000 038208 00 WA 0 0 8\n"
            return "".join(f"   {i}: 20000000 {size} OBJECT GLOBAL DEFAULT 5 {name}\n" for i, (name, size) in enumerate(sizes[variant].items(), 1))
        with patch("verify_build._readelf", side_effect=fake_readelf):
            report = linked_evidence(Path("stock.out"), Path("p009.out"))
        self.assertTrue(report["validated"])
        self.assertEqual(report["bss_delta_bytes"], 704)
        self.assertEqual(report["symbols"]["p009"]["sli_zigbee_multicast_table"], 104)

    def test_ncp_counter_decoder_and_summary(self):
        values = [0] * 42; values[18] = 1; values[27] = 2; values[31] = 3; values[32] = 4; values[33] = 5; values[40] = 6
        rec = decode_line("2026-09-04 10:11:12 info: zh:ember: [NCP COUNTERS] " + ",".join(map(str, values)), source="test.log", line_number=7)
        assert rec is not None
        self.assertEqual(rec["selected"]["BROADCAST_TABLE_FULL"], 5)
        records = []
        for btt in (0, 2, 3):
            v = [0] * 42; v[33] = btt
            r = decode_line("[NCP COUNTERS] " + ",".join(map(str, v)), source="x", line_number=1); assert r is not None; records.append(r)
        report = summary(records)
        self.assertEqual(report["totals"]["BROADCAST_TABLE_FULL"], 5)
        self.assertEqual(report["nonzero_intervals"]["BROADCAST_TABLE_FULL"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
