"""Versioned Zigbee2MQTT fresh-network rebuild/reconciliation helper.

Snapshots application-level Zigbee state needed to reconstruct a fresh network:
IEEE identity, friendly names/options, exact group IDs/memberships,
non-coordinator bindings and cached reporting metadata. Network keys/PAN/
Trust-Center material are never copied into the manifest.

Default commands are read-only. apply is separately gated and executes only an
explicit JSON operation plan over Zigbee2MQTT's documented bridge MQTT API.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
from typing import Any
import zipfile
import yaml

VERSION = "0.1.1"
FORMAT = "p10-z2m-rebuild-manifest-v1"
PLAN_FORMAT = "p10-z2m-rebuild-plan-v1"
APPLY_APPROVAL = "APPLY_P10_REBUILD_RECONCILIATION"
HELPER = Path("C:/Workspace/repos/config/skills/home-assistant-readonly/ha_readonly.py")
ADDON = "45df7312_zigbee2mqtt"
DEVICE_NON_OPTIONS = {"friendly_name", "reporting", "homeassistant"}
GROUP_NON_OPTIONS = {"friendly_name"}
BIND_CLUSTER_NAMES = {5: "genScenes", 6: "genOnOff", 8: "genLevelCtrl", 258: "closuresWindowCovering", 768: "lightingColorCtrl"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _reverse_ieee(ieee: str) -> str:
    raw = ieee.lower().removeprefix("0x")
    if len(raw) != 16:
        return ieee.lower()
    return "0x" + bytes.fromhex(raw)[::-1].hex()


def _load_bundle(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with zipfile.ZipFile(path) as archive:
        required = {"data/configuration.yaml", "data/database.db"}
        if not required <= set(archive.namelist()):
            raise ValueError("Bundle is missing configuration.yaml or database.db")
        config = yaml.safe_load(archive.read("data/configuration.yaml")) or {}
        rows = [json.loads(raw) for raw in archive.read("data/database.db").splitlines() if raw.strip()]
    if not isinstance(config, dict):
        raise ValueError("Zigbee2MQTT configuration is not a mapping")
    return config, rows


def _config_devices(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = config.get("devices") or {}
    if not isinstance(raw, dict):
        raise ValueError("configuration.devices must be a mapping")
    result = {}
    for ieee, options in raw.items():
        if not isinstance(ieee, str) or not isinstance(options, dict):
            raise ValueError("Invalid configuration.devices entry")
        result[ieee.lower()] = options
    return result


def _config_groups(config: dict[str, Any]) -> dict[int, dict[str, Any]]:
    raw = config.get("groups") or {}
    if not isinstance(raw, dict):
        raise ValueError("configuration.groups must be a mapping")
    result = {}
    for group_id, options in raw.items():
        try:
            gid = int(group_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Group IDs must be numeric") from exc
        if not isinstance(options, dict):
            raise ValueError("Invalid configuration.groups entry")
        result[gid] = options
    return result


def _canonical_target(ieee: str, canonical: dict[str, str]) -> str:
    key = ieee.lower()
    if key in canonical:
        return canonical[key]
    rev = _reverse_ieee(key)
    if rev in canonical:
        return canonical[rev]
    return key


def snapshot(bundle: Path) -> dict[str, Any]:
    config, rows = _load_bundle(bundle)
    device_cfg = _config_devices(config)
    group_cfg = _config_groups(config)
    devices_db = {
        row["ieeeAddr"].lower(): row
        for row in rows
        if row.get("type") != "Group" and isinstance(row.get("ieeeAddr"), str)
    }
    coordinators = [ieee for ieee, row in devices_db.items() if row.get("type") == "Coordinator"]
    if len(coordinators) != 1:
        raise ValueError("Expected exactly one coordinator in database")
    coordinator = coordinators[0]

    canonical = {}
    for ieee in devices_db:
        canonical[ieee] = ieee
        canonical[_reverse_ieee(ieee)] = ieee

    groups_db = {
        int(row["groupID"]): row
        for row in rows
        if row.get("type") == "Group" and type(row.get("groupID")) is int
    }
    groups = {}
    for gid in sorted(set(groups_db) | set(group_cfg)):
        db = groups_db.get(gid, {})
        cfg = group_cfg.get(gid, {})
        members = []
        for member in db.get("members") or []:
            raw_ieee = member.get("deviceIeeeAddr")
            endpoint = member.get("endpointID")
            if isinstance(raw_ieee, str) and type(endpoint) is int:
                members.append({"ieee": _canonical_target(raw_ieee, canonical), "endpoint": endpoint})
        groups[str(gid)] = {
            "id": gid,
            "friendly_name": cfg.get("friendly_name") or f"group_{gid}",
            "options": {k: v for k, v in cfg.items() if k not in GROUP_NON_OPTIONS},
            "members": sorted(members, key=lambda x: (x["ieee"], x["endpoint"])),
        }

    device_groups = {ieee: [] for ieee in devices_db}
    for gid_s, group in groups.items():
        for member in group["members"]:
            if member["ieee"] in device_groups:
                device_groups[member["ieee"]].append(
                    {"group_id": int(gid_s), "endpoint": member["endpoint"]}
                )

    devices = {}
    for ieee, db in sorted(devices_db.items()):
        if db.get("type") == "Coordinator":
            continue
        cfg = device_cfg.get(ieee, {})
        endpoints = {}
        for ep_key, ep in sorted((db.get("endpoints") or {}).items(), key=lambda x: int(x[0])):
            if not isinstance(ep, dict):
                continue
            custom_binds, coordinator_binds = [], []
            for bind in ep.get("binds") or []:
                if not isinstance(bind, dict) or type(bind.get("cluster")) is not int:
                    continue
                if bind.get("type") == "group" and type(bind.get("groupID")) is int:
                    custom_binds.append({
                        "target_kind": "group",
                        "target_group_id": bind["groupID"],
                        "target_endpoint": None,
                        "cluster": bind["cluster"],
                    })
                elif bind.get("type") == "endpoint" and isinstance(bind.get("deviceIeeeAddress"), str):
                    target = _canonical_target(bind["deviceIeeeAddress"], canonical)
                    item = {
                        "target_kind": "device",
                        "target_ieee": target,
                        "target_endpoint": bind.get("endpointID"),
                        "cluster": bind["cluster"],
                    }
                    (coordinator_binds if target == coordinator else custom_binds).append(item)
            reporting = []
            for report in ep.get("configuredReportings") or []:
                if not isinstance(report, dict):
                    continue
                if type(report.get("cluster")) is not int or type(report.get("attrId")) is not int:
                    continue
                reporting.append({
                    "cluster": report["cluster"],
                    "attribute": report["attrId"],
                    "minimum_report_interval": report.get("minRepIntval"),
                    "maximum_report_interval": report.get("maxRepIntval"),
                    "reportable_change": report.get("repChange"),
                })
            endpoints[str(ep_key)] = {
                "custom_bindings": custom_binds,
                "coordinator_bindings_reference": coordinator_binds,
                "configured_reportings_reference": reporting,
            }

        devices[ieee] = {
            "ieee": ieee,
            "friendly_name": cfg.get("friendly_name") or ieee,
            "friendly_name_explicit": bool(cfg.get("friendly_name")),
            "role": db.get("type"),
            "model_id": db.get("modelId"),
            "manufacturer_name": db.get("manufName"),
            "software_build_id": db.get("swBuildId"),
            "interview_state": db.get("interviewState"),
            "options": {k: v for k, v in cfg.items() if k not in DEVICE_NON_OPTIONS},
            "configured_reporting_option": cfg.get("reporting"),
            "homeassistant_option": cfg.get("homeassistant"),
            "groups": sorted(device_groups.get(ieee, []), key=lambda x: (x["group_id"], x["endpoint"])),
            "endpoints": endpoints,
        }

    return {
        "format": FORMAT,
        "tool_version": VERSION,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_bundle_sha256": _sha256(bundle),
        "contains_network_secrets": False,
        "source_coordinator_ieee": coordinator,
        "homeassistant_discovery_should_be_disabled_during_identity_restore": True,
        "devices": devices,
        "groups": groups,
    }


def save_new(path: Path, data: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError("Unsupported rebuild manifest")
    if not isinstance(data.get("devices"), dict) or not isinstance(data.get("groups"), dict):
        raise ValueError("Malformed rebuild manifest")
    return data


def select_pilot(manifest: dict[str, Any], selectors: list[str], aliases: list[str]) -> dict[str, Any]:
    alias_map = {}
    for raw in aliases:
        if "=" not in raw:
            raise ValueError("Alias must be IEEE=FRIENDLY_NAME")
        ieee, name = raw.split("=", 1)
        alias_map[ieee.lower()] = name
    by_name = {
        dev["friendly_name"].lower(): ieee
        for ieee, dev in manifest["devices"].items()
        if isinstance(dev.get("friendly_name"), str)
    }
    selected, unresolved = [], []
    for selector in selectors:
        key = selector.lower()
        if key in manifest["devices"]:
            ieee = key
        elif key in by_name:
            ieee = by_name[key]
        else:
            unresolved.append(selector)
            continue
        if ieee not in selected:
            selected.append(ieee)

    devices, needed_groups = {}, set()
    for ieee in selected:
        dev = json.loads(json.dumps(manifest["devices"][ieee]))
        if ieee in alias_map:
            dev["friendly_name"] = alias_map[ieee]
            dev["friendly_name_explicit"] = True
        devices[ieee] = dev
        needed_groups.update(x["group_id"] for x in dev.get("groups") or [])
        for ep in dev.get("endpoints", {}).values():
            for bind in ep.get("custom_bindings") or []:
                if bind.get("target_kind") == "group":
                    needed_groups.add(bind["target_group_id"])
    groups = {
        str(gid): manifest["groups"][str(gid)]
        for gid in sorted(needed_groups)
        if str(gid) in manifest["groups"]
    }
    return {
        "format": FORMAT,
        "tool_version": VERSION,
        "captured_at_utc": manifest["captured_at_utc"],
        "source_bundle_sha256": manifest["source_bundle_sha256"],
        "contains_network_secrets": False,
        "source_coordinator_ieee": manifest["source_coordinator_ieee"],
        "pilot": True,
        "selectors": selectors,
        "unresolved_selectors": unresolved,
        "devices": devices,
        "groups": groups,
    }


def _current_index(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[int, Any]]:
    devices = {
        row["ieeeAddr"].lower(): row
        for row in rows
        if row.get("type") != "Group" and isinstance(row.get("ieeeAddr"), str)
    }
    groups = {
        int(row["groupID"]): row
        for row in rows
        if row.get("type") == "Group" and type(row.get("groupID")) is int
    }
    return devices, groups


def _joined_from_bundle(path: Path) -> tuple[dict[str, Any], dict[int, Any]]:
    _, rows = _load_bundle(path)
    return _current_index(rows)


def _target_name(manifest: dict[str, Any], bind: dict[str, Any]) -> str | None:
    if bind["target_kind"] == "group":
        group = manifest["groups"].get(str(bind["target_group_id"]))
        return None if group is None else group["friendly_name"]
    target = manifest["devices"].get(bind.get("target_ieee"))
    return None if target is None else target["friendly_name"]


def _group_custom_bindings(device: dict[str, Any]) -> list[dict[str, Any]]:
    grouped = {}
    for ep_id, ep in device.get("endpoints", {}).items():
        for bind in ep.get("custom_bindings") or []:
            if bind["target_kind"] == "group":
                key = (int(ep_id), "group", bind["target_group_id"], None)
            else:
                key = (int(ep_id), "device", bind["target_ieee"], bind.get("target_endpoint"))
            grouped.setdefault(key, []).append(bind["cluster"])
    result = []
    for (source_ep, kind, target, target_ep), clusters in sorted(grouped.items(), key=str):
        item = {"source_endpoint": source_ep, "target_kind": kind, "clusters": sorted(set(clusters))}
        if kind == "group":
            item["target_group_id"] = target
        else:
            item["target_ieee"] = target
            item["target_endpoint"] = target_ep
        result.append(item)
    return result


def plan(manifest: dict[str, Any], current_bundle: Path,
         include_reporting: bool = False) -> dict[str, Any]:
    current_config, current_rows = _load_bundle(current_bundle)
    current_devices, current_groups = _current_index(current_rows)
    current_device_cfg = _config_devices(current_config)
    current_group_cfg = _config_groups(current_config)
    operations, deferred, status_map = [], [], {}

    for gid_s, group in sorted(manifest["groups"].items(), key=lambda x: int(x[0])):
        gid = int(gid_s)
        if gid not in current_groups:
            operations.append({
                "scope": "group",
                "topic": "zigbee2mqtt/bridge/request/group/add",
                "payload": {"id": gid, "friendly_name": group["friendly_name"]},
                "reason": "restore_exact_group_id",
            })
        current_gcfg = current_group_cfg.get(gid, {})
        current_gopts = {k: v for k, v in current_gcfg.items() if k not in GROUP_NON_OPTIONS}
        if group.get("options") and current_gopts != group["options"]:
            operations.append({
                "scope": "group",
                "topic": "zigbee2mqtt/bridge/request/group/options",
                "payload": {"id": group["friendly_name"], "options": group["options"]},
                "reason": "restore_group_options",
                "best_effort": True,
            })

    for ieee, desired in sorted(manifest["devices"].items()):
        observed = current_devices.get(ieee)
        if observed is None:
            status_map[ieee] = {"friendly_name": desired["friendly_name"], "state": "NOT_JOINED"}
            continue
        if observed.get("interviewState") not in (None, "SUCCESSFUL") and observed.get("interviewCompleted") is not True:
            status_map[ieee] = {
                "friendly_name": desired["friendly_name"],
                "state": "JOINED_INTERVIEW_INCOMPLETE",
                "interview_state": observed.get("interviewState"),
            }
            continue
        status_map[ieee] = {"friendly_name": desired["friendly_name"], "state": "JOINED"}

        current_cfg = current_device_cfg.get(ieee, {})
        if (desired.get("friendly_name_explicit") and
                current_cfg.get("friendly_name") != desired["friendly_name"]):
            operations.append({
                "scope": ieee,
                "topic": "zigbee2mqtt/bridge/request/device/rename",
                "payload": {"from": ieee, "to": desired["friendly_name"], "homeassistant_rename": False},
                "reason": "restore_friendly_name_by_ieee",
            })
        runtime_options = dict(desired.get("options") or {})
        if desired.get("configured_reporting_option") is not None:
            runtime_options["reporting"] = desired["configured_reporting_option"]
        current_runtime_options = {
            k: v for k, v in current_cfg.items()
            if k not in {"friendly_name", "homeassistant"}
        }
        if runtime_options and current_runtime_options != runtime_options:
            operations.append({
                "scope": ieee,
                "topic": "zigbee2mqtt/bridge/request/device/options",
                "payload": {"id": desired["friendly_name"], "options": runtime_options},
                "reason": "restore_device_options",
                "best_effort": True,
            })
        operations.append({
            "scope": ieee,
            "topic": "zigbee2mqtt/bridge/request/device/configure",
            "payload": {"id": desired["friendly_name"]},
            "reason": "rebuild_converter_managed_bindings_and_reporting",
            "best_effort": True,
        })

        for membership in desired.get("groups") or []:
            group = manifest["groups"].get(str(membership["group_id"]))
            if group is None:
                deferred.append({
                    "scope": ieee, "reason": "group_definition_missing",
                    "group_id": membership["group_id"],
                })
                continue
            existing_members = current_groups.get(membership["group_id"], {}).get("members") or []
            already_member = any(
                isinstance(item, dict)
                and str(item.get("deviceIeeeAddr", "")).lower() == ieee
                and item.get("endpointID") == membership["endpoint"]
                for item in existing_members
            )
            if not already_member:
                payload = {"group": group["friendly_name"], "device": desired["friendly_name"]}
                if membership["endpoint"] != 1:
                    payload["endpoint"] = membership["endpoint"]
                operations.append({
                    "scope": ieee,
                    "topic": "zigbee2mqtt/bridge/request/group/members/add",
                    "payload": payload,
                    "reason": "restore_group_membership",
                })

        for bind in _group_custom_bindings(desired):
            target_name = _target_name(manifest, bind)
            if target_name is None:
                deferred.append({
                    "scope": ieee, "reason": "binding_target_not_in_manifest",
                    "binding": bind,
                })
                continue
            if bind["target_kind"] == "device" and bind["target_ieee"] not in current_devices:
                deferred.append({
                    "scope": ieee, "reason": "binding_target_not_joined",
                    "binding": bind,
                })
                continue
            cluster_names = [BIND_CLUSTER_NAMES.get(cluster) for cluster in bind["clusters"]]
            if any(name is None for name in cluster_names):
                deferred.append({
                    "scope": ieee, "reason": "binding_cluster_not_supported_by_z2m_api",
                    "binding": bind,
                })
                continue
            payload = {
                "from": desired["friendly_name"],
                "from_endpoint": bind["source_endpoint"],
                "to": target_name,
                "clusters": cluster_names,
            }
            if bind["target_kind"] == "device" and bind.get("target_endpoint") is not None:
                payload["to_endpoint"] = bind["target_endpoint"]
            operations.append({
                "scope": ieee,
                "topic": "zigbee2mqtt/bridge/request/device/bind",
                "payload": payload,
                "reason": "restore_non_coordinator_binding",
            })

        if include_reporting:
            for ep_id, ep in desired.get("endpoints", {}).items():
                for report in ep.get("configured_reportings_reference") or []:
                    payload = {
                        "id": desired["friendly_name"],
                        "endpoint": int(ep_id),
                        "cluster": report["cluster"],
                        "attribute": report["attribute"],
                        "minimum_report_interval": report["minimum_report_interval"],
                        "maximum_report_interval": report["maximum_report_interval"],
                    }
                    if report.get("reportable_change") is not None:
                        payload["reportable_change"] = report["reportable_change"]
                    operations.append({
                        "scope": ieee,
                        "topic": "zigbee2mqtt/bridge/request/device/reporting/configure",
                        "payload": payload,
                        "reason": "restore_cached_reporting_reference",
                        "best_effort": True,
                    })

    return {
        "format": PLAN_FORMAT,
        "tool_version": VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_source_bundle_sha256": manifest["source_bundle_sha256"],
        "homeassistant_discovery_should_be_disabled_during_identity_restore": True,
        "reporting_replay_enabled": include_reporting,
        "operations": operations,
        "deferred": deferred,
        "device_status": status_map,
    }


def status(manifest: dict[str, Any], current_bundle: Path) -> dict[str, Any]:
    current_devices, current_groups = _joined_from_bundle(current_bundle)
    joined = successful = 0
    devices = {}
    for ieee, desired in sorted(manifest["devices"].items()):
        row = current_devices.get(ieee)
        if row is None:
            devices[ieee] = {"friendly_name": desired["friendly_name"], "state": "NOT_JOINED"}
            continue
        joined += 1
        ok = row.get("interviewCompleted") is True or row.get("interviewState") == "SUCCESSFUL"
        successful += int(ok)
        devices[ieee] = {
            "friendly_name": desired["friendly_name"],
            "state": "INTERVIEW_SUCCESSFUL" if ok else "JOINED_NOT_READY",
            "role": row.get("type"),
            "model_id": row.get("modelId"),
        }
    return {
        "tool_version": VERSION,
        "expected_devices": len(manifest["devices"]),
        "joined_devices": joined,
        "interview_successful": successful,
        "missing_group_ids": sorted(int(g) for g in manifest["groups"] if int(g) not in current_groups),
        "devices": devices,
    }


REMOTE_APPLY = r"""
import json,re,subprocess,sys,time
ops=json.load(open(sys.argv[1],encoding="utf-8"))
cfg=open("/homeassistant/zigbee2mqtt/configuration.yaml",encoding="utf-8").read()
server=re.search(r"server:\s*mqtt://([^:/\s]+)(?::(\d+))?",cfg)
user=re.search(r"^\s*user:\s*(\S+)",cfg,re.M)
password=re.search(r"^\s*password:\s*(\S+)",cfg,re.M)
base_topic_match=re.search(r"(?ms)^mqtt:\s*\n(?:(?:^[ \t]+.*\n)*)?^[ \t]+base_topic:\s*(\S+)",cfg)
base_topic=base_topic_match.group(1) if base_topic_match else "zigbee2mqtt"
if not server:
    print(json.dumps({"ok":False,"error":"mqtt server not found"})); sys.exit(2)
base=["-h",server.group(1),"-p",server.group(2) or "1883"]
if user:
    if not password:
        print(json.dumps({"ok":False,"error":"mqtt password missing"})); sys.exit(2)
    base += ["-u",user.group(1),"-P",password.group(1)]
results=[]
for idx,op in enumerate(ops):
    topic=op["topic"]
    if topic.startswith("zigbee2mqtt/"):
        topic=base_topic+"/"+topic[len("zigbee2mqtt/"):]
    payload=dict(op["payload"]); tx=710000+idx; payload["transaction"]=tx
    response=topic.replace("/request/","/response/",1)
    sub=subprocess.Popen(["mosquitto_sub"]+base+["-t",response,"-C","1","-W","18"],
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    time.sleep(0.15)
    pub=subprocess.run(["mosquitto_pub"]+base+["-t",topic,"-m",json.dumps(payload)],
                       capture_output=True,text=True,timeout=10)
    if pub.returncode!=0:
        sub.kill(); results.append({"index":idx,"status":"pub_error"}); break
    out,err=sub.communicate(timeout=22)
    try: data=json.loads(out.strip()) if out.strip() else {}
    except ValueError: data={}
    if data.get("transaction") != tx:
        results.append({"index":idx,"status":"response_mismatch"}); break
    results.append({"index":idx,"status":data.get("status","error"),"error":data.get("error")})
    if data.get("status")!="ok" and not op.get("best_effort"):
        break
print(json.dumps({"ok":all(r["status"]=="ok" for r in results),"results":results}))
"""


def apply(plan_data: dict[str, Any], scopes: list[str], approval: str) -> dict[str, Any]:
    if approval != APPLY_APPROVAL:
        raise ValueError("Exact apply approval phrase required")
    if plan_data.get("format") != PLAN_FORMAT:
        raise ValueError("Unsupported operation plan")
    wanted = {x.lower() for x in scopes}
    selected = []
    for op in plan_data.get("operations") or []:
        scope = str(op.get("scope", "")).lower()
        if not wanted or scope in wanted or scope == "group":
            selected.append(op)
    if not selected:
        raise ValueError("No operations selected")

    spec = importlib.util.spec_from_file_location("p10_ha", HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Canonical HA SSH helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.connect("ha")
    remote_py = "/tmp/p10_rebuild_apply.py"
    remote_json = "/tmp/p10_rebuild_ops.json"
    try:
        _, out, _ = client.exec_command(f"ha apps info {ADDON} --raw-json", timeout=20)
        info = json.loads(out.read().decode("utf-8"))
        if out.channel.recv_exit_status() != 0 or info.get("data", {}).get("state") != "started":
            raise RuntimeError("Zigbee2MQTT add-on is not started")
        sftp = client.open_sftp()
        with sftp.open(remote_py, "w") as stream:
            stream.write(REMOTE_APPLY)
        with sftp.open(remote_json, "w") as stream:
            json.dump(selected, stream)
        _, stdout, _ = client.exec_command(
            f"python3 {remote_py} {remote_json}", timeout=max(60, len(selected) * 30)
        )
        raw = stdout.read().decode("utf-8", errors="replace").strip()
        rc = stdout.channel.recv_exit_status()
        result = json.loads(raw) if raw.startswith("{") else {"ok": False, "error": "transport"}
        if rc != 0:
            raise RuntimeError("Remote MQTT reconciliation failed")
        return {"tool_version": VERSION, "operations_selected": len(selected), "remote_result": result}
    finally:
        try:
            client.exec_command(f"rm -f {remote_py} {remote_json}", timeout=10)
        finally:
            client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="action", required=True)

    snap = sub.add_parser("snapshot")
    snap.add_argument("--bundle", required=True, type=Path)
    snap.add_argument("--out", required=True, type=Path)

    pilot = sub.add_parser("pilot")
    pilot.add_argument("--manifest", required=True, type=Path)
    pilot.add_argument("--device", action="append", default=[], required=True)
    pilot.add_argument("--alias", action="append", default=[])
    pilot.add_argument("--out", required=True, type=Path)

    make_plan = sub.add_parser("plan")
    make_plan.add_argument("--manifest", required=True, type=Path)
    make_plan.add_argument("--current-bundle", required=True, type=Path)
    make_plan.add_argument("--include-reporting", action="store_true")
    make_plan.add_argument("--out", required=True, type=Path)

    stat = sub.add_parser("status")
    stat.add_argument("--manifest", required=True, type=Path)
    stat.add_argument("--current-bundle", required=True, type=Path)

    run = sub.add_parser("apply")
    run.add_argument("--plan", required=True, type=Path)
    run.add_argument("--scope", action="append", default=[])
    run.add_argument("--execute", action="store_true")
    run.add_argument("--approval", default="")

    args = parser.parse_args(argv)
    try:
        if args.action == "snapshot":
            result = snapshot(args.bundle)
            save_new(args.out, result)
            summary = {
                "status": "MANIFEST_CREATED", "tool_version": VERSION,
                "devices": len(result["devices"]), "groups": len(result["groups"]),
                "contains_network_secrets": False, "out": str(args.out),
            }
        elif args.action == "pilot":
            result = select_pilot(load_manifest(args.manifest), args.device, args.alias)
            save_new(args.out, result)
            summary = {
                "status": "PILOT_MANIFEST_CREATED", "devices": len(result["devices"]),
                "groups": len(result["groups"]),
                "unresolved_selectors": result["unresolved_selectors"], "out": str(args.out),
            }
        elif args.action == "plan":
            result = plan(load_manifest(args.manifest), args.current_bundle, args.include_reporting)
            save_new(args.out, result)
            summary = {
                "status": "PLAN_CREATED", "operations": len(result["operations"]),
                "deferred": len(result["deferred"]), "out": str(args.out),
            }
        elif args.action == "status":
            summary = status(load_manifest(args.manifest), args.current_bundle)
        else:
            data = json.loads(args.plan.read_text(encoding="utf-8"))
            if not args.execute:
                summary = {
                    "status": "DRY_RUN_ONLY", "tool_version": VERSION,
                    "operation_count": len(data.get("operations") or []),
                    "approval_required": APPLY_APPROVAL,
                }
            else:
                summary = apply(data, args.scope, args.approval)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError,
            json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print("P10_REBUILD_ERROR: " + str(exc)[:220], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
