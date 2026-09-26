from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import p10_rebuild_reconciler as tool

COORD = "0x00124b002d12b1fd"
ROUTER = "0xa4c1380000000001"
REMOTE = "0x08fd52ff00000002"
OTHER = "0xa4c1380000000003"


def _backup(devices=None):
    return {
        "coordinator_ieee": COORD.removeprefix("0x"),
        "pan_id": "0x1234",
        "extended_pan_id": "0011223344556677",
        "channel": 11,
        "network_key": {"key": "00" * 16, "sequence_number": 0, "frame_counter": 1},
        "devices": devices or [],
    }


def bundle(
    path: Path,
    *,
    include_remote: bool = True,
    include_group: bool = True,
    group_name: str = "PilotLights",
    router_options: bool = True,
) -> Path:
    devices = {
        ROUTER: {"friendly_name": "PilotRouter"},
        REMOTE: {"friendly_name": "PilotRemote"},
        OTHER: {"friendly_name": "OtherRouter"},
    }
    if router_options:
        devices[ROUTER].update({
            "retain": True,
            "reporting": [{"attribute": "all", "min_interval": 20, "max_interval": 300}],
        })
    config = {
        "mqtt": {"server": "mqtt://broker:1883", "base_topic": "zigbee2mqtt"},
        "devices": devices,
        "groups": {22: {"friendly_name": group_name, "optimistic": True}},
    }
    rows = [
        {
            "id": 1,
            "type": "Coordinator",
            "ieeeAddr": COORD,
            "interviewCompleted": True,
            "endpoints": {},
        },
        {
            "id": 2,
            "type": "Router",
            "ieeeAddr": ROUTER,
            "modelId": "TS011F",
            "manufName": "_TZ3000_test",
            "interviewCompleted": True,
            "interviewState": "SUCCESSFUL",
            "endpoints": {
                "1": {
                    "binds": [
                        {
                            "cluster": 6,
                            "deviceIeeeAddress": tool._reverse_ieee(COORD),
                            "endpointID": 1,
                            "type": "endpoint",
                        }
                    ],
                    "configuredReportings": [
                        {
                            "cluster": 6,
                            "attrId": 0,
                            "minRepIntval": 5,
                            "maxRepIntval": 300,
                            "repChange": 1,
                        }
                    ],
                }
            },
        },
        {
            "id": 4,
            "type": "Router",
            "ieeeAddr": OTHER,
            "modelId": "TS011F",
            "interviewCompleted": True,
            "interviewState": "SUCCESSFUL",
            "endpoints": {"1": {"binds": [], "configuredReportings": []}},
        },
    ]
    if include_remote:
        rows.append({
            "id": 3,
            "type": "EndDevice",
            "ieeeAddr": REMOTE,
            "modelId": "RODRET wireless dimmer",
            "interviewCompleted": True,
            "interviewState": "SUCCESSFUL",
            "endpoints": {
                "1": {
                    "binds": [
                        {"cluster": 6, "groupID": 22, "type": "group"},
                        {"cluster": 8, "groupID": 22, "type": "group"},
                    ],
                    "configuredReportings": [],
                }
            },
        })
    if include_group:
        rows.append({
            "id": 5,
            "type": "Group",
            "groupID": 22,
            "members": [
                {"deviceIeeeAddr": ROUTER, "endpointID": 1},
                {"deviceIeeeAddr": OTHER, "endpointID": 1},
            ],
            "meta": {},
        })

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "data/configuration.yaml",
            yaml.safe_dump(config, sort_keys=True),
        )
        archive.writestr(
            "data/database.db",
            b"\n".join(
                json.dumps(row, separators=(",", ":")).encode()
                for row in rows
            ) + b"\n",
        )
        archive.writestr(
            "data/coordinator_backup.json",
            json.dumps(_backup()),
        )
    return path


class RebuildReconcilerTests(TestCase):
    def test_snapshot_preserves_application_state_and_network_fingerprint(self):
        with TemporaryDirectory() as td:
            snap = tool.snapshot(bundle(Path(td) / "source.zip"))
        self.assertEqual(tool.VERSION, "0.2.1")
        self.assertFalse(snap["contains_network_secrets"])
        self.assertTrue(snap["source_network_fingerprint"])
        self.assertEqual(snap["groups"]["22"]["friendly_name"], "PilotLights")
        self.assertEqual(
            {(item["ieee"], item["endpoint"]) for item in snap["groups"]["22"]["members"]},
            {(ROUTER, 1), (OTHER, 1)},
        )
        ep = snap["devices"][ROUTER]["endpoints"]["1"]
        self.assertEqual(ep["custom_bindings"], [])
        self.assertEqual(snap["devices"][ROUTER]["options"], {"retain": True})

    def test_pilot_filters_group_members_to_selected_devices(self):
        with TemporaryDirectory() as td:
            snap = tool.snapshot(bundle(Path(td) / "source.zip"))
        pilot = tool.select_pilot(
            snap,
            ["PilotRouter", REMOTE],
            [f"{REMOTE}=RODRET_Pilot_A"],
        )
        self.assertEqual(set(pilot["devices"]), {ROUTER, REMOTE})
        self.assertEqual(pilot["devices"][REMOTE]["friendly_name"], "RODRET_Pilot_A")
        self.assertEqual(
            pilot["groups"]["22"]["members"],
            [{"ieee": ROUTER, "endpoint": 1}],
        )

    def test_unresolved_pilot_selector_fails_closed(self):
        with TemporaryDirectory() as td:
            snap = tool.snapshot(bundle(Path(td) / "source.zip"))
        with self.assertRaisesRegex(ValueError, "Unresolved"):
            tool.select_pilot(snap, ["does-not-exist"], [])

    def test_plan_creates_group_and_binding_without_raw_reporting_replay(self):
        with TemporaryDirectory() as td:
            td = Path(td)
            old = bundle(td / "old.zip")
            fresh0 = bundle(td / "fresh0.zip", include_group=False)
            cfg, rows, backup = tool._load_bundle(fresh0, require_backup=True)
            for row in rows:
                if row.get("ieeeAddr") == REMOTE:
                    row["endpoints"]["1"]["binds"] = []
            fresh = td / "fresh.zip"
            with zipfile.ZipFile(fresh, "w") as archive:
                archive.writestr("data/configuration.yaml", yaml.safe_dump(cfg))
                archive.writestr(
                    "data/database.db",
                    b"\n".join(json.dumps(row).encode() for row in rows) + b"\n",
                )
                archive.writestr("data/coordinator_backup.json", json.dumps(backup))
            manifest = tool.snapshot(old)
            result = tool.plan(manifest, fresh)
        topics = [item["topic"] for item in result["operations"]]
        self.assertIn("zigbee2mqtt/bridge/request/group/add", topics)
        self.assertIn("zigbee2mqtt/bridge/request/device/bind", topics)
        self.assertFalse(any("reporting/configure" in topic for topic in topics))
        self.assertFalse(result["raw_reporting_replay_enabled"])

    def test_plan_restores_group_name_with_rename(self):
        with TemporaryDirectory() as td:
            td = Path(td)
            old = bundle(td / "old.zip", group_name="Desired")
            current = bundle(td / "current.zip", group_name="Wrong")
            manifest = tool.snapshot(old)
            result = tool.plan(manifest, current)
        rename = next(
            item for item in result["operations"]
            if item["topic"].endswith("/group/rename")
        )
        self.assertEqual(rename["payload"]["from"], 22)
        self.assertEqual(rename["payload"]["to"], "Desired")

    def test_network_fingerprint_binds_journal_and_plan(self):
        with TemporaryDirectory() as td:
            td = Path(td)
            source = bundle(td / "source.zip")
            manifest = tool.snapshot(source)
            result = tool.plan(manifest, source)
            journal = tool._new_journal("different")
            path = td / "journal.json"
            path.write_text(json.dumps(journal), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "different Zigbee network"):
                tool.plan(manifest, source, path)
        self.assertTrue(result["network_fingerprint"])

    def test_scope_does_not_pull_unrelated_group_operations(self):
        ops = [
            {
                "scope": "group:22",
                "related_scopes": [ROUTER],
                "op_id": "g1",
            },
            {
                "scope": "group:33",
                "related_scopes": [OTHER],
                "op_id": "g2",
            },
            {"scope": ROUTER, "op_id": "d1"},
        ]
        selected = tool._select_operations({"operations": ops}, [ROUTER])
        self.assertEqual({item["op_id"] for item in selected}, {"g1", "d1"})

    def test_status_checks_real_restoration_not_just_interview(self):
        with TemporaryDirectory() as td:
            td = Path(td)
            old = bundle(td / "old.zip")
            current = bundle(td / "current.zip", router_options=False)
            manifest = tool.snapshot(old)
            result = tool.status(manifest, current)
        router = result["devices"][ROUTER]
        self.assertTrue(router["interview_ok"])
        self.assertFalse(router["options_ok"])
        self.assertFalse(router["fully_restored"])

    def test_reporting_mismatch_is_deferred_not_written(self):
        with TemporaryDirectory() as td:
            td = Path(td)
            old = bundle(td / "old.zip")
            current = bundle(td / "current.zip")
            cfg, rows, backup = tool._load_bundle(current, require_backup=True)
            for row in rows:
                if row.get("ieeeAddr") == ROUTER:
                    row["endpoints"]["1"]["configuredReportings"] = []
            rewritten = td / "no-report.zip"
            with zipfile.ZipFile(rewritten, "w") as archive:
                archive.writestr("data/configuration.yaml", yaml.safe_dump(cfg))
                archive.writestr(
                    "data/database.db",
                    b"\n".join(json.dumps(row).encode() for row in rows) + b"\n",
                )
                archive.writestr("data/coordinator_backup.json", json.dumps(backup))
            result = tool.plan(tool.snapshot(old), rewritten)
        self.assertTrue(any(
            item["reason"] == "reporting_reference_mismatch_use_configure_then_review"
            for item in result["deferred"]
        ))
        self.assertFalse(any(
            item["topic"].endswith("/reporting/configure")
            for item in result["operations"]
        ))

    def test_broker_parser_refuses_mqtts_instead_of_guessing(self):
        with self.assertRaisesRegex(ValueError, "Only mqtt"):
            tool._broker_from_config({"mqtt": {"server": "mqtts://broker:8883"}})

    def test_remote_apply_compiles(self):
        compile(tool.REMOTE_APPLY, "<remote_apply>", "exec")

    def test_journal_atomic_roundtrip(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "journal.json"
            data = tool._new_journal("abc")
            tool._atomic_json(path, data)
            loaded = tool._load_journal(path, "abc")
        self.assertEqual(loaded["network_fingerprint"], "abc")
