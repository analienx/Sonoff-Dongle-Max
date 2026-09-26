from __future__ import annotations
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
import zipfile
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import p10_rebuild_reconciler as tool


COORD = "0x00124b002d12b1fd"
COORD_REV = "0xfdb1122d004b1200"
ROUTER = "0xa4c1380000000001"
REMOTE = "0x08fd52ff00000002"


def bundle(path: Path, include_remote: bool = True, include_group: bool = True) -> Path:
    config = {
        "devices": {
            ROUTER: {
                "friendly_name": "PilotRouter",
                "retain": True,
                "reporting": [{"attribute": "all", "min_interval": 20, "max_interval": 300}],
            },
            REMOTE: {"friendly_name": "PilotRemote"},
        },
        "groups": {22: {"friendly_name": "PilotLights", "optimistic": True}},
    }
    rows = [
        {
            "id": 1, "type": "Coordinator", "ieeeAddr": COORD,
            "interviewCompleted": True, "endpoints": {},
        },
        {
            "id": 2, "type": "Router", "ieeeAddr": ROUTER, "modelId": "TS011F",
            "manufName": "_TZ3000_test", "interviewCompleted": True,
            "interviewState": "SUCCESSFUL",
            "endpoints": {
                "1": {
                    "binds": [
                        {"cluster": 6, "deviceIeeeAddress": COORD_REV,
                         "endpointID": 1, "type": "endpoint"},
                    ],
                    "configuredReportings": [
                        {"cluster": 6, "attrId": 0, "minRepIntval": 5,
                         "maxRepIntval": 300, "repChange": 1},
                    ],
                }
            },
        },
    ]
    if include_remote:
        rows.append({
            "id": 3, "type": "EndDevice", "ieeeAddr": REMOTE,
            "modelId": "RODRET wireless dimmer", "interviewCompleted": True,
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
            "id": 4, "type": "Group", "groupID": 22,
            "members": [{"deviceIeeeAddr": ROUTER, "endpointID": 1}],
            "meta": {},
        })
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/configuration.yaml", yaml.safe_dump(config, sort_keys=True))
        archive.writestr(
            "data/database.db",
            b"\n".join(json.dumps(row, separators=(",", ":")).encode() for row in rows) + b"\n",
        )
    return path


class RebuildReconcilerTests(TestCase):
    def test_snapshot_preserves_group_and_separates_coordinator_binding(self):
        with TemporaryDirectory() as td:
            source = bundle(Path(td) / "source.zip")
            snap = tool.snapshot(source)
        self.assertEqual(tool.VERSION, "0.1.1")
        self.assertFalse(snap["contains_network_secrets"])
        self.assertEqual(snap["groups"]["22"]["friendly_name"], "PilotLights")
        self.assertEqual(snap["groups"]["22"]["members"],
                         [{"ieee": ROUTER, "endpoint": 1}])
        ep = snap["devices"][ROUTER]["endpoints"]["1"]
        self.assertEqual(ep["custom_bindings"], [])
        self.assertEqual(ep["coordinator_bindings_reference"][0]["target_ieee"], COORD)
        self.assertEqual(snap["devices"][ROUTER]["options"], {"retain": True})

    def test_snapshot_keeps_custom_group_bindings_exactly(self):
        with TemporaryDirectory() as td:
            snap = tool.snapshot(bundle(Path(td) / "source.zip"))
        binds = snap["devices"][REMOTE]["endpoints"]["1"]["custom_bindings"]
        self.assertEqual(
            {(b["target_group_id"], b["cluster"]) for b in binds},
            {(22, 6), (22, 8)},
        )

    def test_pilot_selector_accepts_names_and_aliases(self):
        with TemporaryDirectory() as td:
            snap = tool.snapshot(bundle(Path(td) / "source.zip"))
        pilot = tool.select_pilot(
            snap,
            ["PilotRouter", REMOTE],
            [f"{REMOTE}=RODRET_Pilot_A"],
        )
        self.assertEqual(set(pilot["devices"]), {ROUTER, REMOTE})
        self.assertEqual(pilot["devices"][REMOTE]["friendly_name"], "RODRET_Pilot_A")
        self.assertEqual(pilot["unresolved_selectors"], [])
        self.assertIn("22", pilot["groups"])

    def test_plan_uses_exact_group_id_and_replays_custom_binding(self):
        with TemporaryDirectory() as td:
            td = Path(td)
            original = bundle(td / "old.zip")
            current = bundle(td / "new.zip")
            snap = tool.snapshot(original)
            # Simulate a fresh network without the old group but with both devices joined.
            current = bundle(td / "fresh.zip", include_group=False)
            result = tool.plan(snap, current)
        topics = [x["topic"] for x in result["operations"]]
        self.assertIn("zigbee2mqtt/bridge/request/group/add", topics)
        group_add = next(x for x in result["operations"] if x["topic"].endswith("/group/add"))
        self.assertEqual(group_add["payload"], {"id": 22, "friendly_name": "PilotLights"})
        bind = next(x for x in result["operations"] if x["topic"].endswith("/device/bind"))
        self.assertEqual(bind["payload"]["clusters"], ["genOnOff", "genLevelCtrl"])
        self.assertEqual(bind["payload"]["from"], "PilotRemote")
        self.assertEqual(bind["payload"]["from_endpoint"], 1)
        self.assertEqual(bind["payload"]["to"], "PilotLights")
        self.assertFalse(any(
            x["scope"] == ROUTER and x["topic"].endswith("/device/options")
            for x in result["operations"]
        ))

    def test_plan_replays_missing_runtime_options(self):
        with TemporaryDirectory() as td:
            td = Path(td)
            source = bundle(td / "old.zip")
            fresh = bundle(td / "fresh.zip")
            snap = tool.snapshot(source)
            cfg, rows = tool._load_bundle(fresh)
            cfg["devices"][ROUTER] = {"friendly_name": "PilotRouter"}
            rewritten = td / "fresh-no-options.zip"
            with zipfile.ZipFile(rewritten, "w") as archive:
                archive.writestr("data/configuration.yaml", yaml.safe_dump(cfg, sort_keys=True))
                archive.writestr("data/database.db", b"\n".join(
                    json.dumps(r, separators=(",", ":")).encode() for r in rows) + b"\n")
            result = tool.plan(snap, rewritten)
        router_options = next(x for x in result["operations"]
                              if x["scope"] == ROUTER and x["topic"].endswith("/device/options"))
        self.assertTrue(router_options["best_effort"])
        self.assertTrue(router_options["payload"]["options"]["retain"])
        self.assertIn("reporting", router_options["payload"]["options"])

    def test_plan_defers_device_binding_until_target_joins(self):
        manifest = {
            "format": tool.FORMAT,
            "tool_version": tool.VERSION,
            "captured_at_utc": "2026-09-26T00:00:00+00:00",
            "source_bundle_sha256": "0" * 64,
            "source_coordinator_ieee": COORD,
            "devices": {
                REMOTE: {
                    "ieee": REMOTE, "friendly_name": "Remote",
                    "friendly_name_explicit": True, "options": {}, "groups": [],
                    "endpoints": {"1": {"custom_bindings": [{
                        "target_kind": "device", "target_ieee": ROUTER,
                        "target_endpoint": 1, "cluster": 6,
                    }], "configured_reportings_reference": []}},
                },
                ROUTER: {
                    "ieee": ROUTER, "friendly_name": "Router",
                    "friendly_name_explicit": True, "options": {}, "groups": [],
                    "endpoints": {},
                },
            },
            "groups": {},
        }
        with TemporaryDirectory() as td:
            current = bundle(Path(td) / "fresh.zip", include_remote=True)
            # Remove target router from fresh DB while keeping remote.
            cfg, rows = tool._load_bundle(current)
            rows = [r for r in rows if r.get("ieeeAddr") != ROUTER]
            current2 = Path(td) / "fresh2.zip"
            with zipfile.ZipFile(current2, "w") as archive:
                archive.writestr("data/configuration.yaml", yaml.safe_dump(cfg))
                archive.writestr("data/database.db", b"\n".join(
                    json.dumps(r).encode() for r in rows) + b"\n")
            result = tool.plan(manifest, current2)
        self.assertTrue(any(x["reason"] == "binding_target_not_joined"
                            for x in result["deferred"]))

    def test_reporting_is_opt_in(self):
        with TemporaryDirectory() as td:
            td = Path(td)
            source = bundle(td / "old.zip")
            fresh = bundle(td / "fresh.zip")
            snap = tool.snapshot(source)
            default = tool.plan(snap, fresh, include_reporting=False)
            enabled = tool.plan(snap, fresh, include_reporting=True)
        self.assertFalse(any(x["topic"].endswith("/reporting/configure")
                             for x in default["operations"]))
        report = next(x for x in enabled["operations"]
                      if x["topic"].endswith("/reporting/configure"))
        self.assertEqual(report["payload"]["cluster"], 6)
        self.assertEqual(report["payload"]["attribute"], 0)


    def test_remote_apply_supports_nondefault_base_topic(self):
        compile(tool.REMOTE_APPLY, "<remote_apply>", "exec")
        self.assertIn('base_topic', tool.REMOTE_APPLY)
        self.assertIn('topic.startswith("zigbee2mqtt/")', tool.REMOTE_APPLY)

    def test_apply_is_fail_closed_without_exact_phrase(self):
        with self.assertRaisesRegex(ValueError, "approval"):
            tool.apply({"format": tool.PLAN_FORMAT, "operations": []}, [],
                       "wrong")
