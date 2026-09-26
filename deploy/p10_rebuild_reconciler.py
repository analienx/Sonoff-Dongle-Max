"""Versioned Zigbee2MQTT fresh-network rebuild/reconciliation helper.

The manifest is application state only. It never copies Zigbee network keys.
Every executable plan is bound to a specific coordinator/PAN/extPAN/channel
fingerprint and live execution requires a persistent per-operation journal.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p10_rebuild_common import backup_network_fingerprint

VERSION = "0.2.0"
FORMAT = "p10-z2m-rebuild-manifest-v1"
PLAN_FORMAT = "p10-z2m-rebuild-plan-v2"
JOURNAL_FORMAT = "p10-z2m-rebuild-journal-v1"
APPLY_APPROVAL = "APPLY_P10_REBUILD_RECONCILIATION"
HELPER = Path("C:/Workspace/repos/config/skills/home-assistant-readonly/ha_readonly.py")
ADDON = "45df7312_zigbee2mqtt"
DEVICE_NON_OPTIONS = {"friendly_name", "reporting", "homeassistant"}
GROUP_NON_OPTIONS = {"friendly_name"}
BIND_CLUSTER_NAMES = {
    5: "genScenes",
    6: "genOnOff",
    8: "genLevelCtrl",
    258: "closuresWindowCovering",
    768: "lightingColorCtrl",
}


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
    try:
        return "0x" + bytes.fromhex(raw)[::-1].hex()
    except ValueError:
        return ieee.lower()


def _load_bundle(path: Path, require_backup: bool = False) -> tuple[dict, list[dict], dict | None]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {"data/configuration.yaml", "data/database.db"}
        if not required <= names:
            raise ValueError("Bundle is missing configuration.yaml or database.db")
        config = yaml.safe_load(archive.read("data/configuration.yaml")) or {}
        rows = [
            json.loads(raw)
            for raw in archive.read("data/database.db").splitlines()
            if raw.strip()
        ]
        backup = None
        if "data/coordinator_backup.json" in names:
            backup = json.loads(archive.read("data/coordinator_backup.json"))
        elif require_backup:
            raise ValueError("Bundle is missing coordinator_backup.json")
    if not isinstance(config, dict):
        raise TypeError("Zigbee2MQTT configuration is not a mapping")
    if backup is not None and not isinstance(backup, dict):
        raise TypeError("Coordinator backup is not a mapping")
    return config, rows, backup


def _config_devices(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = config.get("devices") or {}
    if not isinstance(raw, dict):
        raise TypeError("configuration.devices must be a mapping")
    result = {}
    for ieee, options in raw.items():
        if not isinstance(ieee, str) or not isinstance(options, dict):
            raise TypeError("Invalid configuration.devices entry")
        result[ieee.lower()] = options
    return result


def _config_groups(config: dict[str, Any]) -> dict[int, dict[str, Any]]:
    raw = config.get("groups") or {}
    if not isinstance(raw, dict):
        raise TypeError("configuration.groups must be a mapping")
    result = {}
    for group_id, options in raw.items():
        try:
            gid = int(group_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Group IDs must be numeric") from exc
        if not isinstance(options, dict):
            raise TypeError("Invalid configuration.groups entry")
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
    config, rows, backup = _load_bundle(bundle, require_backup=True)
    assert backup is not None
    device_cfg = _config_devices(config)
    group_cfg = _config_groups(config)
    devices_db = {
        row["ieeeAddr"].lower(): row
        for row in rows
        if row.get("type") != "Group" and isinstance(row.get("ieeeAddr"), str)
    }
    coordinators = [
        ieee for ieee, row in devices_db.items() if row.get("type") == "Coordinator"
    ]
    if len(coordinators) != 1:
        raise ValueError("Expected exactly one coordinator in database")
    coordinator = coordinators[0]

    canonical: dict[str, str] = {}
    for ieee in devices_db:
        canonical[ieee] = ieee
        canonical[_reverse_ieee(ieee)] = ieee

    groups_db = {
        int(row["groupID"]): row
        for row in rows
        if row.get("type") == "Group" and type(row.get("groupID")) is int
    }
    groups: dict[str, dict] = {}
    for gid in sorted(set(groups_db) | set(group_cfg)):
        db = groups_db.get(gid, {})
        cfg = group_cfg.get(gid, {})
        members = []
        for member in db.get("members") or []:
            raw_ieee = member.get("deviceIeeeAddr")
            endpoint = member.get("endpointID")
            if isinstance(raw_ieee, str) and type(endpoint) is int:
                members.append({
                    "ieee": _canonical_target(raw_ieee, canonical),
                    "endpoint": endpoint,
                })
        groups[str(gid)] = {
            "id": gid,
            "friendly_name": cfg.get("friendly_name") or f"group_{gid}",
            "options": {
                key: value
                for key, value in cfg.items()
                if key not in GROUP_NON_OPTIONS
            },
            "members": sorted(members, key=lambda item: (item["ieee"], item["endpoint"])),
        }

    device_groups = {ieee: [] for ieee in devices_db}
    for gid_s, group in groups.items():
        for member in group["members"]:
            if member["ieee"] in device_groups:
                device_groups[member["ieee"]].append({
                    "group_id": int(gid_s),
                    "endpoint": member["endpoint"],
                })

    devices: dict[str, dict] = {}
    for ieee, db in sorted(devices_db.items()):
        if db.get("type") == "Coordinator":
            continue
        cfg = device_cfg.get(ieee, {})
        endpoints = {}
        for ep_key, ep in sorted(
            (db.get("endpoints") or {}).items(), key=lambda item: int(item[0])
        ):
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
                elif (
                    bind.get("type") == "endpoint"
                    and isinstance(bind.get("deviceIeeeAddress"), str)
                ):
                    target = _canonical_target(bind["deviceIeeeAddress"], canonical)
                    item = {
                        "target_kind": "device",
                        "target_ieee": target,
                        "target_endpoint": bind.get("endpointID"),
                        "cluster": bind["cluster"],
                    }
                    (
                        coordinator_binds
                        if target == coordinator
                        else custom_binds
                    ).append(item)

            reporting = []
            for report in ep.get("configuredReportings") or []:
                if not isinstance(report, dict):
                    continue
                if (
                    type(report.get("cluster")) is not int
                    or type(report.get("attrId")) is not int
                ):
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
            "options": {
                key: value
                for key, value in cfg.items()
                if key not in DEVICE_NON_OPTIONS
            },
            "configured_reporting_option": cfg.get("reporting"),
            "homeassistant_option": cfg.get("homeassistant"),
            "groups": sorted(
                device_groups.get(ieee, []),
                key=lambda item: (item["group_id"], item["endpoint"]),
            ),
            "endpoints": endpoints,
        }

    names = [item["friendly_name"].lower() for item in devices.values()]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate friendly names found; manifest would be ambiguous")

    return {
        "format": FORMAT,
        "tool_version": VERSION,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_bundle_sha256": _sha256(bundle),
        "source_network_fingerprint": backup_network_fingerprint(backup),
        "contains_network_secrets": False,
        "source_coordinator_ieee": coordinator,
        "devices": devices,
        "groups": groups,
    }


def save_new(path: Path, data: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError("Unsupported rebuild manifest")
    if not isinstance(data.get("devices"), dict) or not isinstance(data.get("groups"), dict):
        raise TypeError("Malformed rebuild manifest")
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

    if unresolved:
        raise ValueError("Unresolved pilot selectors: " + ", ".join(unresolved))

    devices, needed_groups = {}, set()
    for ieee in selected:
        dev = json.loads(json.dumps(manifest["devices"][ieee]))
        if ieee in alias_map:
            dev["friendly_name"] = alias_map[ieee]
            dev["friendly_name_explicit"] = True
        devices[ieee] = dev
        needed_groups.update(item["group_id"] for item in dev.get("groups") or [])
        for ep in dev.get("endpoints", {}).values():
            for bind in ep.get("custom_bindings") or []:
                if bind.get("target_kind") == "group":
                    needed_groups.add(bind["target_group_id"])

    pilot_names = [item["friendly_name"].lower() for item in devices.values()]
    if len(pilot_names) != len(set(pilot_names)):
        raise ValueError("Pilot aliases create duplicate friendly names")

    groups = {}
    selected_set = set(selected)
    for gid in sorted(needed_groups):
        source = manifest["groups"].get(str(gid))
        if source is None:
            continue
        group = json.loads(json.dumps(source))
        group["members"] = [
            member for member in group.get("members") or []
            if member.get("ieee") in selected_set
        ]
        groups[str(gid)] = group

    return {
        "format": FORMAT,
        "tool_version": VERSION,
        "captured_at_utc": manifest["captured_at_utc"],
        "source_bundle_sha256": manifest["source_bundle_sha256"],
        "source_network_fingerprint": manifest.get("source_network_fingerprint"),
        "contains_network_secrets": False,
        "source_coordinator_ieee": manifest["source_coordinator_ieee"],
        "pilot": True,
        "selectors": selectors,
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


def _canonical_map(devices: dict[str, Any], coordinator: str) -> dict[str, str]:
    result = {}
    for ieee in set(devices) | {coordinator}:
        result[ieee] = ieee
        result[_reverse_ieee(ieee)] = ieee
    return result


def _desired_bind_groups(device: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple, set[int]] = {}
    for ep_id, ep in device.get("endpoints", {}).items():
        for bind in ep.get("custom_bindings") or []:
            if bind["target_kind"] == "group":
                key = (int(ep_id), "group", bind["target_group_id"], None)
            else:
                key = (
                    int(ep_id),
                    "device",
                    bind["target_ieee"],
                    bind.get("target_endpoint"),
                )
            grouped.setdefault(key, set()).add(bind["cluster"])
    result = []
    for (source_ep, kind, target, target_ep), clusters in sorted(grouped.items(), key=str):
        item = {
            "source_endpoint": source_ep,
            "target_kind": kind,
            "clusters": sorted(clusters),
        }
        if kind == "group":
            item["target_group_id"] = target
        else:
            item["target_ieee"] = target
            item["target_endpoint"] = target_ep
        result.append(item)
    return result


def _current_custom_bind_set(
    row: dict,
    devices: dict[str, Any],
    coordinator: str,
) -> set[tuple]:
    canonical = _canonical_map(devices, coordinator)
    result = set()
    for ep_id, ep in (row.get("endpoints") or {}).items():
        if not isinstance(ep, dict):
            continue
        for bind in ep.get("binds") or []:
            if not isinstance(bind, dict) or type(bind.get("cluster")) is not int:
                continue
            if bind.get("type") == "group" and type(bind.get("groupID")) is int:
                result.add((int(ep_id), "group", bind["groupID"], None, bind["cluster"]))
            elif (
                bind.get("type") == "endpoint"
                and isinstance(bind.get("deviceIeeeAddress"), str)
            ):
                target = _canonical_target(bind["deviceIeeeAddress"], canonical)
                if target == coordinator:
                    continue
                result.add((
                    int(ep_id),
                    "device",
                    target,
                    bind.get("endpointID"),
                    bind["cluster"],
                ))
    return result


def _desired_custom_bind_set(device: dict) -> set[tuple]:
    result = set()
    for ep_id, ep in device.get("endpoints", {}).items():
        for bind in ep.get("custom_bindings") or []:
            if bind["target_kind"] == "group":
                result.add((
                    int(ep_id),
                    "group",
                    bind["target_group_id"],
                    None,
                    bind["cluster"],
                ))
            else:
                result.add((
                    int(ep_id),
                    "device",
                    bind["target_ieee"],
                    bind.get("target_endpoint"),
                    bind["cluster"],
                ))
    return result


def _current_reporting_set(row: dict) -> set[tuple]:
    result = set()
    for ep_id, ep in (row.get("endpoints") or {}).items():
        if not isinstance(ep, dict):
            continue
        for report in ep.get("configuredReportings") or []:
            if (
                isinstance(report, dict)
                and type(report.get("cluster")) is int
                and type(report.get("attrId")) is int
            ):
                result.add((
                    int(ep_id),
                    report["cluster"],
                    report["attrId"],
                    report.get("minRepIntval"),
                    report.get("maxRepIntval"),
                    report.get("repChange"),
                ))
    return result


def _desired_reporting_set(device: dict) -> set[tuple]:
    result = set()
    for ep_id, ep in device.get("endpoints", {}).items():
        for report in ep.get("configured_reportings_reference") or []:
            result.add((
                int(ep_id),
                report["cluster"],
                report["attribute"],
                report.get("minimum_report_interval"),
                report.get("maximum_report_interval"),
                report.get("reportable_change"),
            ))
    return result


def _op_id(scope: str, topic: str, payload: dict, reason: str) -> str:
    raw = json.dumps(
        {"scope": scope, "topic": topic, "payload": payload, "reason": reason},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def _operation(
    scope: str,
    topic: str,
    payload: dict,
    reason: str,
    *,
    related_scopes: list[str] | None = None,
    continue_on_failure: bool = False,
) -> dict:
    item = {
        "scope": scope,
        "topic": topic,
        "payload": payload,
        "reason": reason,
        "continue_on_failure": continue_on_failure,
    }
    if related_scopes:
        item["related_scopes"] = sorted(set(related_scopes))
    item["op_id"] = _op_id(scope, topic, payload, reason)
    return item


def _new_journal(network_fingerprint: str) -> dict:
    return {
        "format": JOURNAL_FORMAT,
        "tool_version": VERSION,
        "network_fingerprint": network_fingerprint,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed": {},
        "failures": [],
    }


def _load_journal(path: Path | None, network_fingerprint: str) -> dict:
    if path is None or not path.exists():
        return _new_journal(network_fingerprint)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != JOURNAL_FORMAT:
        raise ValueError("Unsupported rebuild journal")
    if data.get("network_fingerprint") != network_fingerprint:
        raise RuntimeError("Rebuild journal belongs to a different Zigbee network")
    if not isinstance(data.get("completed"), dict) or not isinstance(data.get("failures"), list):
        raise TypeError("Malformed rebuild journal")
    return data


def _group_related_scopes(manifest: dict, group_id: int) -> list[str]:
    related = {
        member["ieee"]
        for member in manifest["groups"].get(str(group_id), {}).get("members") or []
        if isinstance(member.get("ieee"), str)
    }
    for ieee, device in manifest["devices"].items():
        for ep in device.get("endpoints", {}).values():
            if any(
                bind.get("target_kind") == "group"
                and bind.get("target_group_id") == group_id
                for bind in ep.get("custom_bindings") or []
            ):
                related.add(ieee)
    return sorted(related)


def plan(
    manifest: dict[str, Any],
    current_bundle: Path,
    journal_path: Path | None = None,
) -> dict[str, Any]:
    current_config, current_rows, current_backup = _load_bundle(
        current_bundle, require_backup=True
    )
    assert current_backup is not None
    network_fingerprint = backup_network_fingerprint(current_backup)
    journal = _load_journal(journal_path, network_fingerprint)
    completed = set(journal["completed"])

    current_devices, current_groups = _current_index(current_rows)
    current_device_cfg = _config_devices(current_config)
    current_group_cfg = _config_groups(current_config)
    current_coordinator = "0x" + str(current_backup["coordinator_ieee"]).lower().removeprefix("0x")
    operations, deferred, status_map = [], [], {}

    def add(item: dict) -> None:
        if item["op_id"] not in completed:
            operations.append(item)

    for gid_s, group in sorted(manifest["groups"].items(), key=lambda item: int(item[0])):
        gid = int(gid_s)
        related = _group_related_scopes(manifest, gid)
        existing = current_groups.get(gid)
        current_cfg = current_group_cfg.get(gid, {})
        if existing is None:
            add(_operation(
                f"group:{gid}",
                "zigbee2mqtt/bridge/request/group/add",
                {"id": gid, "friendly_name": group["friendly_name"]},
                "restore_exact_group_id",
                related_scopes=related,
            ))
        elif current_cfg.get("friendly_name") not in (None, group["friendly_name"]):
            add(_operation(
                f"group:{gid}",
                "zigbee2mqtt/bridge/request/group/rename",
                {
                    "from": gid,
                    "to": group["friendly_name"],
                    "homeassistant_rename": False,
                },
                "restore_group_friendly_name",
                related_scopes=related,
            ))

        current_options = {
            key: value
            for key, value in current_cfg.items()
            if key not in GROUP_NON_OPTIONS
        }
        if group.get("options") and current_options != group["options"]:
            add(_operation(
                f"group:{gid}",
                "zigbee2mqtt/bridge/request/group/options",
                {"id": group["friendly_name"], "options": group["options"]},
                "restore_group_options",
                related_scopes=related,
            ))

    for ieee, desired in sorted(manifest["devices"].items()):
        observed = current_devices.get(ieee)
        if observed is None:
            status_map[ieee] = {
                "friendly_name": desired["friendly_name"],
                "state": "NOT_JOINED",
            }
            continue

        interview_ok = (
            observed.get("interviewCompleted") is True
            or observed.get("interviewState") == "SUCCESSFUL"
        )
        if not interview_ok:
            status_map[ieee] = {
                "friendly_name": desired["friendly_name"],
                "state": "JOINED_INTERVIEW_INCOMPLETE",
                "interview_state": observed.get("interviewState"),
            }
            continue
        status_map[ieee] = {
            "friendly_name": desired["friendly_name"],
            "state": "JOINED",
        }

        cfg = current_device_cfg.get(ieee, {})
        if (
            desired.get("friendly_name_explicit")
            and cfg.get("friendly_name") != desired["friendly_name"]
        ):
            add(_operation(
                ieee,
                "zigbee2mqtt/bridge/request/device/rename",
                {
                    "from": ieee,
                    "to": desired["friendly_name"],
                    "homeassistant_rename": False,
                },
                "restore_friendly_name_by_ieee",
            ))

        runtime_options = dict(desired.get("options") or {})
        if desired.get("configured_reporting_option") is not None:
            runtime_options["reporting"] = desired["configured_reporting_option"]
        current_runtime_options = {
            key: value
            for key, value in cfg.items()
            if key not in {"friendly_name", "homeassistant"}
        }
        if runtime_options and current_runtime_options != runtime_options:
            add(_operation(
                ieee,
                "zigbee2mqtt/bridge/request/device/options",
                {"id": desired["friendly_name"], "options": runtime_options},
                "restore_device_options",
            ))

        if desired.get("homeassistant_option") not in (None, {}):
            deferred.append({
                "scope": ieee,
                "reason": "per_device_homeassistant_option_requires_review",
                "value": desired["homeassistant_option"],
            })

        # Configure once per network/journal. This is important for sleepy
        # devices: failed attempts remain unjournalled and are retryable.
        add(_operation(
            ieee,
            "zigbee2mqtt/bridge/request/device/configure",
            {"id": desired["friendly_name"]},
            "run_converter_configure_once",
            continue_on_failure=True,
        ))

        for membership in desired.get("groups") or []:
            group = manifest["groups"].get(str(membership["group_id"]))
            if group is None:
                deferred.append({
                    "scope": ieee,
                    "reason": "group_definition_missing",
                    "group_id": membership["group_id"],
                })
                continue
            existing_members = current_groups.get(
                membership["group_id"], {}
            ).get("members") or []
            already_member = any(
                isinstance(item, dict)
                and str(item.get("deviceIeeeAddr", "")).lower() == ieee
                and item.get("endpointID") == membership["endpoint"]
                for item in existing_members
            )
            if not already_member:
                payload = {
                    "group": group["friendly_name"],
                    "device": desired["friendly_name"],
                }
                if membership["endpoint"] != 1:
                    payload["endpoint"] = membership["endpoint"]
                add(_operation(
                    ieee,
                    "zigbee2mqtt/bridge/request/group/members/add",
                    payload,
                    "restore_group_membership",
                ))

        current_binds = _current_custom_bind_set(
            observed, current_devices, current_coordinator
        )
        desired_binds = _desired_custom_bind_set(desired)
        missing_binds = desired_binds - current_binds
        for bind_group in _desired_bind_groups(desired):
            wanted_tuples = set()
            for cluster in bind_group["clusters"]:
                if bind_group["target_kind"] == "group":
                    wanted_tuples.add((
                        bind_group["source_endpoint"],
                        "group",
                        bind_group["target_group_id"],
                        None,
                        cluster,
                    ))
                else:
                    wanted_tuples.add((
                        bind_group["source_endpoint"],
                        "device",
                        bind_group["target_ieee"],
                        bind_group.get("target_endpoint"),
                        cluster,
                    ))
            missing_clusters = sorted(
                item[-1] for item in (wanted_tuples & missing_binds)
            )
            if not missing_clusters:
                continue

            if bind_group["target_kind"] == "group":
                target = manifest["groups"].get(str(bind_group["target_group_id"]))
                if target is None:
                    deferred.append({
                        "scope": ieee,
                        "reason": "binding_group_target_missing",
                        "binding": bind_group,
                    })
                    continue
                target_name = target["friendly_name"]
            else:
                target = manifest["devices"].get(bind_group["target_ieee"])
                if target is None:
                    deferred.append({
                        "scope": ieee,
                        "reason": "binding_device_target_not_in_manifest",
                        "binding": bind_group,
                    })
                    continue
                if bind_group["target_ieee"] not in current_devices:
                    deferred.append({
                        "scope": ieee,
                        "reason": "binding_device_target_not_joined",
                        "binding": bind_group,
                    })
                    continue
                target_name = target["friendly_name"]

            cluster_names = [BIND_CLUSTER_NAMES.get(cluster) for cluster in missing_clusters]
            if any(name is None for name in cluster_names):
                deferred.append({
                    "scope": ieee,
                    "reason": "binding_cluster_not_supported_by_reconciler",
                    "clusters": missing_clusters,
                    "binding": bind_group,
                })
                continue

            payload = {
                "from": desired["friendly_name"],
                "from_endpoint": bind_group["source_endpoint"],
                "to": target_name,
                "clusters": cluster_names,
            }
            if (
                bind_group["target_kind"] == "device"
                and bind_group.get("target_endpoint") is not None
            ):
                payload["to_endpoint"] = bind_group["target_endpoint"]
            add(_operation(
                ieee,
                "zigbee2mqtt/bridge/request/device/bind",
                payload,
                "restore_missing_non_coordinator_binding",
            ))

        desired_reporting = _desired_reporting_set(desired)
        if desired_reporting and not desired_reporting <= _current_reporting_set(observed):
            deferred.append({
                "scope": ieee,
                "reason": "reporting_reference_mismatch_use_configure_then_review",
                "missing_count": len(
                    desired_reporting - _current_reporting_set(observed)
                ),
            })

    return {
        "format": PLAN_FORMAT,
        "tool_version": VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "network_fingerprint": network_fingerprint,
        "manifest_source_bundle_sha256": manifest["source_bundle_sha256"],
        "operations": operations,
        "deferred": deferred,
        "device_status": status_map,
        "journal_completed_count": len(completed),
        "raw_reporting_replay_enabled": False,
    }


def _normalize_group_members(group: dict) -> set[tuple[str, int]]:
    return {
        (str(item.get("deviceIeeeAddr", "")).lower(), item.get("endpointID"))
        for item in group.get("members") or []
        if isinstance(item, dict)
    }


def status(manifest: dict[str, Any], current_bundle: Path) -> dict[str, Any]:
    config, rows, backup = _load_bundle(current_bundle, require_backup=True)
    assert backup is not None
    current_devices, current_groups = _current_index(rows)
    device_cfg = _config_devices(config)
    group_cfg = _config_groups(config)
    coordinator = "0x" + str(backup["coordinator_ieee"]).lower().removeprefix("0x")

    device_results = {}
    fully_restored = 0
    for ieee, desired in sorted(manifest["devices"].items()):
        row = current_devices.get(ieee)
        if row is None:
            device_results[ieee] = {
                "friendly_name": desired["friendly_name"],
                "joined": False,
                "fully_restored": False,
            }
            continue

        cfg = device_cfg.get(ieee, {})
        interview_ok = (
            row.get("interviewCompleted") is True
            or row.get("interviewState") == "SUCCESSFUL"
        )
        name_ok = (
            not desired.get("friendly_name_explicit")
            or cfg.get("friendly_name") == desired["friendly_name"]
        )
        desired_options = dict(desired.get("options") or {})
        if desired.get("configured_reporting_option") is not None:
            desired_options["reporting"] = desired["configured_reporting_option"]
        current_options = {
            key: value
            for key, value in cfg.items()
            if key not in {"friendly_name", "homeassistant"}
        }
        options_ok = current_options == desired_options

        groups_ok = True
        for membership in desired.get("groups") or []:
            members = _normalize_group_members(
                current_groups.get(membership["group_id"], {})
            )
            if (ieee, membership["endpoint"]) not in members:
                groups_ok = False
                break

        bindings_ok = _desired_custom_bind_set(desired) <= _current_custom_bind_set(
            row, current_devices, coordinator
        )
        reporting_ok = _desired_reporting_set(desired) <= _current_reporting_set(row)
        homeassistant_review = desired.get("homeassistant_option") not in (None, {})
        restored = (
            interview_ok
            and name_ok
            and options_ok
            and groups_ok
            and bindings_ok
            and reporting_ok
            and not homeassistant_review
        )
        fully_restored += int(restored)
        device_results[ieee] = {
            "friendly_name": desired["friendly_name"],
            "joined": True,
            "interview_ok": interview_ok,
            "name_ok": name_ok,
            "options_ok": options_ok,
            "groups_ok": groups_ok,
            "custom_bindings_ok": bindings_ok,
            "reporting_reference_ok": reporting_ok,
            "homeassistant_option_review_required": homeassistant_review,
            "fully_restored": restored,
            "role": row.get("type"),
            "model_id": row.get("modelId"),
        }

    group_results = {}
    for gid_s, desired in sorted(manifest["groups"].items(), key=lambda item: int(item[0])):
        gid = int(gid_s)
        row = current_groups.get(gid)
        cfg = group_cfg.get(gid, {})
        current_options = {
            key: value for key, value in cfg.items() if key not in GROUP_NON_OPTIONS
        }
        expected_members = {
            (member["ieee"], member["endpoint"])
            for member in desired.get("members") or []
        }
        current_members = _normalize_group_members(row or {})
        group_results[gid_s] = {
            "exists": row is not None,
            "name_ok": cfg.get("friendly_name") in (None, desired["friendly_name"])
            if row is not None else False,
            "options_ok": current_options == (desired.get("options") or {}),
            "expected_members_present": expected_members <= current_members,
        }

    return {
        "tool_version": VERSION,
        "network_fingerprint": backup_network_fingerprint(backup),
        "expected_devices": len(manifest["devices"]),
        "joined_devices": sum(item["joined"] for item in device_results.values()),
        "fully_restored_devices": fully_restored,
        "devices": device_results,
        "groups": group_results,
    }


REMOTE_APPLY = r"""
import json,subprocess,sys,time
envelope=json.load(open(sys.argv[1],encoding="utf-8"))
broker=envelope["broker"]
ops=envelope["operations"]
base=["-h",broker["host"],"-p",str(broker["port"])]
if broker.get("user") is not None:
    base += ["-u",broker["user"],"-P",broker["password"]]
results=[]
for index,op in enumerate(ops):
    topic=op["topic"]
    base_topic=envelope["base_topic"]
    if topic.startswith("zigbee2mqtt/"):
        topic=base_topic+"/"+topic[len("zigbee2mqtt/"):]
    payload=dict(op["payload"])
    tx=810000+index
    payload["transaction"]=tx
    response=topic.replace("/request/","/response/",1)
    subscriber=subprocess.Popen(
        ["mosquitto_sub"]+base+["-t",response,"-C","1","-W","20"],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
    )
    time.sleep(0.15)
    publisher=subprocess.run(
        ["mosquitto_pub"]+base+["-t",topic,"-m",json.dumps(payload)],
        capture_output=True,text=True,timeout=12,
    )
    if publisher.returncode!=0:
        subscriber.kill()
        results.append({"op_id":op["op_id"],"status":"publish_error"})
        if not op.get("continue_on_failure"):
            break
        continue
    try:
        out,err=subscriber.communicate(timeout=24)
    except subprocess.TimeoutExpired:
        subscriber.kill(); subscriber.communicate()
        results.append({"op_id":op["op_id"],"status":"response_timeout"})
        if not op.get("continue_on_failure"):
            break
        continue
    try:
        data=json.loads(out.strip()) if out.strip() else {}
    except ValueError:
        data={}
    if data.get("transaction")!=tx:
        results.append({"op_id":op["op_id"],"status":"response_mismatch"})
        if not op.get("continue_on_failure"):
            break
        continue
    results.append({
        "op_id":op["op_id"],
        "status":data.get("status","error"),
        "error":data.get("error"),
    })
    if data.get("status")!="ok" and not op.get("continue_on_failure"):
        break
print(json.dumps({"results":results}))
"""


def _select_operations(plan_data: dict, scopes: list[str]) -> list[dict]:
    wanted = {item.lower() for item in scopes}
    if not wanted:
        return list(plan_data.get("operations") or [])
    selected = []
    for op in plan_data.get("operations") or []:
        scope = str(op.get("scope", "")).lower()
        if scope in wanted:
            selected.append(op)
            continue
        related = {
            str(item).lower() for item in op.get("related_scopes") or []
        }
        if related & wanted:
            selected.append(op)
    return selected


def _broker_from_config(config: dict) -> tuple[dict, str]:
    mqtt = config.get("mqtt") or {}
    if not isinstance(mqtt, dict):
        raise TypeError("mqtt configuration is not a mapping")
    server = mqtt.get("server")
    if not isinstance(server, str):
        raise TypeError("mqtt.server is unavailable")
    parsed = urlparse(server)
    if parsed.scheme != "mqtt" or not parsed.hostname:
        raise ValueError("Only mqtt:// broker transport is supported by reconciler apply")
    user = mqtt.get("user")
    password = mqtt.get("password")
    if user is not None and (not isinstance(user, str) or not isinstance(password, str)):
        raise ValueError("MQTT username/password must be resolved strings")
    base_topic = mqtt.get("base_topic") or "zigbee2mqtt"
    if not isinstance(base_topic, str):
        raise TypeError("mqtt.base_topic is invalid")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 1883,
        "user": user,
        "password": password,
    }, base_topic


def _load_live_backup_and_config(client) -> tuple[dict, dict]:
    sftp = client.open_sftp()
    roots = ("/config/zigbee2mqtt", "/homeassistant/zigbee2mqtt")
    found = []
    for root in roots:
        try:
            with sftp.open(root + "/configuration.yaml", "rb") as stream:
                cfg = yaml.safe_load(stream.read())
            with sftp.open(root + "/coordinator_backup.json", "rb") as stream:
                backup = json.loads(stream.read().decode("utf-8"))
            if isinstance(cfg, dict) and isinstance(backup, dict):
                found.append((cfg, backup))
        except FileNotFoundError:
            continue
    if len(found) != 1:
        raise RuntimeError("Unable to identify a unique live Zigbee2MQTT data root")
    return found[0]


def apply(
    plan_data: dict[str, Any],
    scopes: list[str],
    approval: str,
    journal_path: Path,
) -> dict[str, Any]:
    if approval != APPLY_APPROVAL:
        raise ValueError("Exact apply approval phrase required")
    if plan_data.get("format") != PLAN_FORMAT:
        raise ValueError("Unsupported operation plan")
    expected_fingerprint = plan_data.get("network_fingerprint")
    if not isinstance(expected_fingerprint, str):
        raise TypeError("Plan has no network fingerprint")

    selected = _select_operations(plan_data, scopes)
    if not selected:
        raise ValueError("No operations selected")
    journal = _load_journal(journal_path, expected_fingerprint)

    spec = importlib.util.spec_from_file_location("p10_ha", HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Canonical HA SSH helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.connect("ha")
    remote_json = "/tmp/p10_rebuild_apply_" + os.urandom(6).hex() + ".json"
    remote_py = "/tmp/p10_rebuild_apply_" + os.urandom(6).hex() + ".py"

    try:
        from p10_data_bundle import addon_info

        info = addon_info(client)
        if info.get("state") != "started":
            raise RuntimeError("Zigbee2MQTT add-on is not started")

        live_config, live_backup = _load_live_backup_and_config(client)
        live_fingerprint = backup_network_fingerprint(live_backup)
        if live_fingerprint != expected_fingerprint:
            raise RuntimeError("Plan belongs to a different live Zigbee network")

        broker, base_topic = _broker_from_config(live_config)
        envelope = {
            "broker": broker,
            "base_topic": base_topic,
            "operations": selected,
        }
        sftp = client.open_sftp()
        with sftp.open(remote_py, "w") as stream:
            stream.write(REMOTE_APPLY)
        with sftp.open(remote_json, "w") as stream:
            json.dump(envelope, stream)

        _, stdout, _ = client.exec_command(
            f"python3 {remote_py} {remote_json}",
            timeout=max(90, len(selected) * 35),
        )
        raw = stdout.read().decode("utf-8", errors="replace").strip()
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            raise RuntimeError("Remote MQTT reconciliation transport failed")
        response = json.loads(raw)
        results = response.get("results")
        if not isinstance(results, list):
            raise TypeError("Remote MQTT reconciliation returned malformed results")

        by_id = {op["op_id"]: op for op in selected}
        failures = []
        for result in results:
            op_id = result.get("op_id")
            if op_id not in by_id:
                failures.append({"op_id": op_id, "status": "unknown_result"})
                continue
            if result.get("status") == "ok":
                journal["completed"][op_id] = {
                    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                    "scope": by_id[op_id]["scope"],
                    "reason": by_id[op_id]["reason"],
                }
            else:
                failures.append(result)

        returned_ids = {item.get("op_id") for item in results}
        for op in selected:
            if op["op_id"] not in returned_ids:
                failures.append({
                    "op_id": op["op_id"],
                    "status": "not_executed_after_prior_failure",
                })

        if failures:
            journal["failures"].append({
                "at_utc": datetime.now(timezone.utc).isoformat(),
                "failures": failures,
            })
        journal["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(journal_path, journal)

        if failures:
            raise RuntimeError(
                f"Reconciliation incomplete: {len(failures)} operation(s) failed; "
                "successful operations were journalled for safe retry"
            )

        return {
            "tool_version": VERSION,
            "network_fingerprint_verified": True,
            "operations_selected": len(selected),
            "operations_completed": len(selected),
            "journal": str(journal_path),
            "all_operations_succeeded": True,
        }
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
    make_plan.add_argument("--journal", type=Path)
    make_plan.add_argument("--include-reporting", action="store_true")
    make_plan.add_argument("--out", required=True, type=Path)

    stat_cmd = sub.add_parser("status")
    stat_cmd.add_argument("--manifest", required=True, type=Path)
    stat_cmd.add_argument("--current-bundle", required=True, type=Path)

    run = sub.add_parser("apply")
    run.add_argument("--plan", required=True, type=Path)
    run.add_argument("--journal", required=True, type=Path)
    run.add_argument("--scope", action="append", default=[])
    run.add_argument("--execute", action="store_true")
    run.add_argument("--approval", default="")

    args = parser.parse_args(argv)
    try:
        if args.action == "snapshot":
            result = snapshot(args.bundle)
            save_new(args.out, result)
            summary = {
                "status": "MANIFEST_CREATED",
                "tool_version": VERSION,
                "devices": len(result["devices"]),
                "groups": len(result["groups"]),
                "contains_network_secrets": False,
                "out": str(args.out),
            }
        elif args.action == "pilot":
            result = select_pilot(load_manifest(args.manifest), args.device, args.alias)
            save_new(args.out, result)
            summary = {
                "status": "PILOT_MANIFEST_CREATED",
                "devices": len(result["devices"]),
                "groups": len(result["groups"]),
                "out": str(args.out),
            }
        elif args.action == "plan":
            if args.include_reporting:
                raise ValueError(
                    "Raw reporting replay is disabled in v0.2; use device/configure "
                    "and status verification instead"
                )
            result = plan(
                load_manifest(args.manifest),
                args.current_bundle,
                args.journal,
            )
            save_new(args.out, result)
            summary = {
                "status": "PLAN_CREATED",
                "operations": len(result["operations"]),
                "deferred": len(result["deferred"]),
                "network_fingerprint": result["network_fingerprint"],
                "out": str(args.out),
            }
        elif args.action == "status":
            summary = status(load_manifest(args.manifest), args.current_bundle)
        else:
            data = json.loads(args.plan.read_text(encoding="utf-8"))
            if not args.execute:
                summary = {
                    "status": "DRY_RUN_ONLY",
                    "tool_version": VERSION,
                    "operation_count": len(
                        _select_operations(data, args.scope)
                    ),
                    "network_fingerprint": data.get("network_fingerprint"),
                    "journal": str(args.journal),
                    "approval_required": APPLY_APPROVAL,
                }
            else:
                summary = apply(
                    data,
                    args.scope,
                    args.approval,
                    args.journal,
                )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError,
            json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print("P10_REBUILD_ERROR: " + str(exc)[:300], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
