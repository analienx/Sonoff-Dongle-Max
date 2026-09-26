"""Fail-closed fresh-network pilot state machine for MR4U CC2674P10.

This tool DOES NOT sanitize P10 NVRAM. A live cutover is refused unless a
separate sanitation-evidence document proves the adapter was wiped and empty.
Rollback means logical Zigbee2MQTT/coordinator-backup restoration, not a
byte-for-byte radio-NVRAM rollback.

No command opens permit-join.
"""
from __future__ import annotations

import argparse
import json
import re
import stat
import sys
import time
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p10_data_bundle import addon_info, load_ha
from p10_rebuild_common import (
    atomic_replace,
    backup_device_ieees,
    backup_network_fingerprint,
    cold_bundle_material,
    ensure_quiescent,
    ensure_started,
    find_root,
    remove_regular_if_present,
    replace_addon_options,
    restore_all_data_files,
    sha256_file,
)

VERSION = "0.2.0"
CUTOVER_APPROVAL = "FORM_FRESH_P10_PILOT_NETWORK_AFTER_NV_SANITATION"
ROLLBACK_APPROVAL = "RESTORE_PRE_PILOT_P10_LOGICAL_STATE"
PILOT_BASE_TOPIC = "zigbee2mqtt_p10_pilot"
PILOT_DISCOVERY_TOPIC = "homeassistant_p10_pilot"
PILOT_STATUS_TOPIC = "homeassistant_p10_pilot/status"
ACTIVE_STATE = ("database.db", "database.db.backup", "coordinator_backup.json", "state.json")
SANITATION_FORMAT = "p10-nv-sanitation-evidence-v1"
EXPECTED_ZNP_REVISION = 20260310

TABLE_PATTERNS = {
    "address_manager": re.compile(r"fetched adapter address manager table \(capacity=(\d+), used=(\d+)\)"),
    "security_manager": re.compile(r"fetched adapter security manager table \(capacity=(\d+), used=(\d+)\)"),
    "aps_link_key_data": re.compile(r"fetched adapter aps link key data table \(capacity=(\d+), used=(\d+)\)"),
    "tclk": re.compile(r"fetched adapter tclk table \(capacity=(\d+), used=(\d+)\)"),
    "network_security_material": re.compile(
        r"fetched adapter network security material table \(capacity=(\d+), used=(\d+)\)"
    ),
}


def _load_yaml(raw: bytes) -> dict:
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise TypeError("Zigbee2MQTT configuration is not a mapping")
    return data


def _database_ordinary_count(raw: bytes) -> int:
    count = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("type") not in ("Coordinator", "Group"):
            count += 1
    return count


def _pilot_config(source: dict) -> dict:
    cfg = json.loads(json.dumps(source))
    serial = cfg.get("serial")
    if not isinstance(serial, dict) or serial.get("adapter") != "zstack":
        raise ValueError("Live configuration is not P10/Z-Stack")
    if not str(serial.get("port", "")).startswith("/dev/serial/by-id/"):
        raise ValueError("Pilot requires stable /dev/serial/by-id transport")

    cfg.pop("devices", None)
    cfg.pop("groups", None)

    # The official HA add-on forces HOMEASSISTANT_ENABLED=true in its entrypoint.
    # Isolate discovery rather than pretending it can be disabled in YAML.
    home = cfg.setdefault("homeassistant", {})
    if not isinstance(home, dict):
        raise TypeError("homeassistant configuration is not a mapping")
    home["enabled"] = True
    home["discovery_topic"] = PILOT_DISCOVERY_TOPIC
    home["status_topic"] = PILOT_STATUS_TOPIC

    mqtt = cfg.setdefault("mqtt", {})
    if not isinstance(mqtt, dict):
        raise TypeError("mqtt configuration is not a mapping")
    mqtt["base_topic"] = PILOT_BASE_TOPIC

    advanced = cfg.setdefault("advanced", {})
    if not isinstance(advanced, dict):
        raise TypeError("advanced configuration is not a mapping")
    advanced["channel"] = 11
    advanced["network_key"] = "GENERATE"
    advanced["pan_id"] = "GENERATE"
    advanced["ext_pan_id"] = "GENERATE"
    advanced["log_level"] = "debug"
    return cfg


def _read_live_config(sftp, root: str) -> tuple[bytes, dict]:
    with sftp.open(root + "/configuration.yaml", "rb") as stream:
        raw = stream.read(4 * 1024 * 1024)
    return raw, _load_yaml(raw)


def _recent_log_texts(sftp, root: str, limit: int = 8) -> list[str]:
    log_root = root + "/log"
    try:
        dirs = [
            item for item in sftp.listdir_attr(log_root)
            if stat.S_ISDIR(item.st_mode)
        ]
    except FileNotFoundError:
        return []
    ordered = sorted(
        dirs, key=lambda item: (item.st_mtime, item.filename), reverse=True
    )[:limit]
    texts = []
    for item in ordered:
        path = log_root + "/" + item.filename + "/log.log"
        try:
            with sftp.open(path, "rb") as stream:
                raw = stream.read(16 * 1024 * 1024)
        except FileNotFoundError:
            continue
        texts.append(raw.decode("utf-8", errors="replace"))
    return texts


def _table_counts_from_log(text: str) -> dict:
    result = {}
    for name, pattern in TABLE_PATTERNS.items():
        matches = list(pattern.finditer(text))
        if matches:
            match = matches[-1]
            result[name] = {
                "capacity": int(match.group(1)),
                "used": int(match.group(2)),
            }
    return result


def _live_snapshot(client) -> dict:
    sftp = client.open_sftp()
    root = find_root(sftp)
    _, cfg = _read_live_config(sftp, root)

    backup = None
    try:
        with sftp.open(root + "/coordinator_backup.json", "rb") as stream:
            backup = json.loads(stream.read().decode("utf-8"))
    except FileNotFoundError:
        pass

    ordinary = None
    try:
        with sftp.open(root + "/database.db", "rb") as stream:
            ordinary = _database_ordinary_count(stream.read())
    except FileNotFoundError:
        pass

    counts = {}
    for text in _recent_log_texts(sftp, root):
        observed = _table_counts_from_log(text)
        for name, value in observed.items():
            counts.setdefault(name, value)
        if len(counts) == len(TABLE_PATTERNS):
            break

    return {
        "root": root,
        "addon_state": addon_info(client).get("state"),
        "configuration": cfg,
        "backup": backup,
        "ordinary_devices": ordinary,
        "table_counts": counts,
    }


def _safe_status(snapshot: dict) -> dict:
    cfg = snapshot["configuration"]
    home = cfg.get("homeassistant") or {}
    mqtt = cfg.get("mqtt") or {}
    advanced = cfg.get("advanced") or {}
    backup = snapshot.get("backup")
    tables = snapshot.get("table_counts") or {}
    device_entries = None if not isinstance(backup, dict) else len(backup.get("devices") or [])

    table_clean = all(
        tables.get(name, {}).get("used") == 0
        for name in ("address_manager", "security_manager", "aps_link_key_data", "tclk")
    )
    table_evidence_complete = all(
        name in tables
        for name in ("address_manager", "security_manager", "aps_link_key_data", "tclk")
    )

    return {
        "tool_version": VERSION,
        "addon_state": snapshot["addon_state"],
        "base_topic": mqtt.get("base_topic"),
        "discovery_topic": home.get("discovery_topic") if isinstance(home, dict) else None,
        "channel": advanced.get("channel"),
        "ordinary_devices": snapshot.get("ordinary_devices"),
        "coordinator_backup_device_entries": device_entries,
        "adapter_table_counts": tables,
        "adapter_table_evidence_complete": table_evidence_complete,
        "adapter_device_security_tables_clean": table_evidence_complete and table_clean,
        "fresh_prejoin_state_clean": (
            device_entries == 0 and table_evidence_complete and table_clean
        ),
        "permit_join_opened_by_tool": False,
    }


def _validate_sanitation_evidence(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != SANITATION_FORMAT:
        raise ValueError("Unsupported sanitation evidence format")
    if data.get("znp_revision") != EXPECTED_ZNP_REVISION:
        raise ValueError("Sanitation evidence is for a different ZNP revision")
    if data.get("network_formed") is not False:
        raise ValueError("Sanitation evidence must prove NetworkNotFormed")
    required_zero = {
        "address_manager_used": 0,
        "security_manager_used": 0,
        "aps_link_key_data_used": 0,
        "tclk_used": 0,
    }
    for key, value in required_zero.items():
        if data.get(key) != value:
            raise ValueError("Sanitation evidence does not prove zero " + key)
    created = data.get("created_at_utc")
    if not isinstance(created, str):
        raise TypeError("Sanitation evidence timestamp missing")
    return data


def preflight(bundle: Path, expected_sha256: str, sanitation_evidence: Path | None = None) -> dict:
    if sha256_file(bundle) != expected_sha256:
        raise RuntimeError("Cold bundle SHA-256 mismatch")
    material = cold_bundle_material(bundle)
    evidence = None if sanitation_evidence is None else _validate_sanitation_evidence(sanitation_evidence)

    client = load_ha()
    try:
        info = addon_info(client)
        sftp = client.open_sftp()
        root = find_root(sftp)
        live_raw, live_cfg = _read_live_config(sftp, root)
        live_options = info.get("options")
        if live_raw != material["configuration_raw"]:
            raise RuntimeError("Live configuration differs from cold rollback point")
        if live_options != material["addon_options"]:
            raise RuntimeError("Live add-on options differ from cold rollback point")
        staged = _pilot_config(live_cfg)
        return {
            "tool_version": VERSION,
            "cold_bundle_verified": True,
            "cold_bundle_sha256_match": True,
            "addon_state": info.get("state"),
            "data_root": root,
            "pilot_base_topic": staged["mqtt"]["base_topic"],
            "pilot_discovery_topic": staged["homeassistant"]["discovery_topic"],
            "pilot_channel": staged["advanced"]["channel"],
            "sanitation_evidence_verified": evidence is not None,
            "safe_to_cutover": evidence is not None and info.get("state") == "started",
            "production_changed": False,
        }
    finally:
        client.close()


def verify_fresh(client, old_material: dict) -> dict:
    snapshot = _live_snapshot(client)
    status = _safe_status(snapshot)
    cfg = snapshot["configuration"]
    backup = snapshot.get("backup")
    if snapshot["addon_state"] != "started":
        raise RuntimeError("Fresh pilot add-on is not started")
    if not isinstance(backup, dict):
        raise TypeError("Fresh coordinator backup not yet available")

    home = cfg.get("homeassistant") or {}
    mqtt = cfg.get("mqtt") or {}
    advanced = cfg.get("advanced") or {}
    if mqtt.get("base_topic") != PILOT_BASE_TOPIC:
        raise RuntimeError("Pilot MQTT base topic is not isolated")
    if not isinstance(home, dict) or home.get("discovery_topic") != PILOT_DISCOVERY_TOPIC:
        raise RuntimeError("Pilot Home Assistant discovery topic is not isolated")
    if advanced.get("channel") != 11:
        raise RuntimeError("Fresh pilot is not on channel 11")
    if any(advanced.get(key) == "GENERATE" for key in ("network_key", "pan_id", "ext_pan_id")):
        raise RuntimeError("Generated network identity was not materialized")
    if snapshot.get("ordinary_devices") != 0:
        raise RuntimeError("Fresh database already contains ordinary devices")
    if len(backup.get("devices") or []) != 0:
        raise RuntimeError("P10 coordinator backup is not clean: stale device entries remain")

    old_backup = old_material["coordinator_backup"]
    if backup_network_fingerprint(backup) == backup_network_fingerprint(old_backup):
        raise RuntimeError("Fresh pilot retained the old network identity")
    if backup_device_ieees(backup) & backup_device_ieees(old_backup):
        raise RuntimeError("Fresh pilot retained old coordinator device IEEE entries")

    tables = status["adapter_table_counts"]
    for name in ("address_manager", "security_manager", "aps_link_key_data", "tclk"):
        if name not in tables:
            raise RuntimeError("Missing adapter-table evidence for " + name)
        if tables[name]["used"] != 0:
            raise RuntimeError(name + " is not empty after fresh commissioning")

    return {
        **status,
        "fresh_network_verified": True,
        "network_fingerprint": backup_network_fingerprint(backup),
        "network_identity_changed": True,
        "logical_cold_rollback_available": True,
    }


def cutover(
    bundle: Path,
    expected_sha256: str,
    sanitation_evidence: Path,
    approval: str,
) -> dict:
    if approval != CUTOVER_APPROVAL:
        raise ValueError("Exact cutover approval phrase required")
    preflight(bundle, expected_sha256, sanitation_evidence)
    material = cold_bundle_material(bundle)

    client = load_ha()
    changed = False
    try:
        ensure_quiescent(client)
        sftp = client.open_sftp()
        root = find_root(sftp)
        live_raw, live_cfg = _read_live_config(sftp, root)
        if live_raw != material["configuration_raw"]:
            raise RuntimeError("Live config changed after stop; refusing cutover")
        if addon_info(client).get("options") != material["addon_options"]:
            raise RuntimeError("Add-on options changed after stop; refusing cutover")

        pilot_raw = yaml.safe_dump(
            _pilot_config(live_cfg), sort_keys=False, allow_unicode=True
        ).encode("utf-8")
        atomic_replace(sftp, root + "/configuration.yaml", pilot_raw)
        for name in ACTIVE_STATE:
            remove_regular_if_present(sftp, root + "/" + name)
        changed = True

        ensure_started(client)
        deadline = time.monotonic() + 120
        last_error = None
        while time.monotonic() < deadline:
            try:
                return {
                    "status": "FRESH_P10_PILOT_ACTIVE",
                    **verify_fresh(client, material),
                }
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                time.sleep(2)

        # Never auto-rollback through a startup race. Freeze and require the
        # explicit rollback command, which has its own preconditions.
        ensure_quiescent(client)
        raise RuntimeError(
            "Fresh verification failed; add-on left STOPPED for explicit recovery: "
            + str(last_error)[:180]
        )
    except Exception:
        if changed:
            try:
                ensure_quiescent(client)
            except Exception as freeze_exc:
                raise RuntimeError(
                    "Cutover failed and add-on could not be safely frozen: "
                    + str(freeze_exc)[:160]
                ) from freeze_exc
        raise
    finally:
        client.close()


def _verify_logical_rollback(client, material: dict) -> dict:
    snapshot = _live_snapshot(client)
    if snapshot["addon_state"] != "started":
        raise RuntimeError("Rollback add-on did not start")
    backup = snapshot.get("backup")
    if not isinstance(backup, dict):
        raise TypeError("Rollback coordinator backup not available")

    old_backup = material["coordinator_backup"]
    identity_fields = ("coordinator_ieee", "pan_id", "extended_pan_id", "channel")
    for field in identity_fields:
        if backup.get(field) != old_backup.get(field):
            raise RuntimeError("Rollback network identity mismatch: " + field)
    old_key = (old_backup.get("network_key") or {}).get("key")
    new_key = (backup.get("network_key") or {}).get("key")
    if old_key != new_key:
        raise RuntimeError("Rollback network key mismatch")

    old_db = material["data_files"]["database.db"]
    live_count = snapshot.get("ordinary_devices")
    old_count = _database_ordinary_count(old_db)
    if live_count != old_count:
        raise RuntimeError(
            f"Rollback database device count mismatch ({live_count} != {old_count})"
        )
    old_ieees = backup_device_ieees(old_backup)
    live_ieees = backup_device_ieees(backup)
    if not old_ieees <= live_ieees:
        raise RuntimeError("Rollback coordinator backup lost expected device registrations")
    if addon_info(client).get("options") != material["addon_options"]:
        raise RuntimeError("Rollback add-on options mismatch")

    return {
        "logical_rollback_verified": True,
        "network_fingerprint": backup_network_fingerprint(backup),
        "coordinator_ieee_restored": True,
        "network_identity_restored": True,
        "database_ordinary_devices": live_count,
        "expected_backup_device_entries_present": len(old_ieees),
        "raw_radio_nvram_restored": False,
    }


def rollback_preflight(bundle: Path, expected_sha256: str) -> dict:
    if sha256_file(bundle) != expected_sha256:
        raise RuntimeError("Cold bundle SHA-256 mismatch")
    material = cold_bundle_material(bundle)
    old_backup = material["coordinator_backup"]
    old_db = material["data_files"]["database.db"]

    client = load_ha()
    try:
        info = addon_info(client)
        sftp = client.open_sftp()
        root = find_root(sftp)
        return {
            "tool_version": VERSION,
            "cold_bundle_verified": True,
            "cold_bundle_sha256_match": True,
            "live_addon_state": info.get("state"),
            "live_data_root": root,
            "addon_options_already_match": (
                info.get("options") == material["addon_options"]
            ),
            "target_network_fingerprint": backup_network_fingerprint(old_backup),
            "target_coordinator_ieee": old_backup.get("coordinator_ieee"),
            "target_channel": old_backup.get("channel"),
            "target_database_ordinary_devices": _database_ordinary_count(old_db),
            "target_backup_device_entries": len(old_backup.get("devices") or []),
            "raw_radio_nvram_restore_claimed": False,
            "safe_to_attempt_logical_rollback": True,
            "live_change_performed": False,
        }
    finally:
        client.close()


def rollback(bundle: Path, expected_sha256: str, approval: str) -> dict:
    if approval != ROLLBACK_APPROVAL:
        raise ValueError("Exact rollback approval phrase required")
    if sha256_file(bundle) != expected_sha256:
        raise RuntimeError("Cold bundle SHA-256 mismatch")
    material = cold_bundle_material(bundle)

    client = load_ha()
    try:
        ensure_quiescent(client)
        info = addon_info(client)
        current_options = info.get("options")
        if not isinstance(current_options, dict):
            raise TypeError("Live add-on options unavailable")
        if current_options != material["addon_options"]:
            replace_addon_options(client, current_options, material["addon_options"])

        sftp = client.open_sftp()
        root = find_root(sftp)
        restore_all_data_files(sftp, root, material)
        ensure_started(client)

        deadline = time.monotonic() + 150
        last_error = None
        while time.monotonic() < deadline:
            try:
                return {
                    "status": "PRE_PILOT_P10_LOGICAL_STATE_RESTORED",
                    **_verify_logical_rollback(client, material),
                }
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                time.sleep(2)

        ensure_quiescent(client)
        raise RuntimeError(
            "Logical rollback verification failed; add-on left STOPPED: "
            + str(last_error)[:180]
        )
    finally:
        client.close()


def status() -> dict:
    client = load_ha()
    try:
        snapshot = _live_snapshot(client)
        result = _safe_status(snapshot)
        backup = snapshot.get("backup")
        if isinstance(backup, dict):
            result["network_fingerprint"] = backup_network_fingerprint(backup)
            result["coordinator_ieee"] = backup.get("coordinator_ieee")
        return result
    finally:
        client.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="action", required=True)

    q = sub.add_parser("status")

    q = sub.add_parser("rollback-preflight")
    q.add_argument("--bundle", required=True, type=Path)
    q.add_argument("--sha256", required=True)

    for name in ("preflight", "cutover", "rollback"):
        q = sub.add_parser(name)
        q.add_argument("--bundle", required=True, type=Path)
        q.add_argument("--sha256", required=True)
        q.add_argument("--approval", default="")
        if name in ("preflight", "cutover"):
            q.add_argument("--sanitation-evidence", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            result = status()
        elif args.action == "rollback-preflight":
            result = rollback_preflight(args.bundle, args.sha256)
        elif args.action == "preflight":
            result = preflight(args.bundle, args.sha256, args.sanitation_evidence)
        elif args.action == "cutover":
            if args.sanitation_evidence is None:
                raise ValueError("--sanitation-evidence is required for cutover")
            result = cutover(
                args.bundle,
                args.sha256,
                args.sanitation_evidence,
                args.approval,
            )
        else:
            result = rollback(args.bundle, args.sha256, args.approval)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError,
            json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print("P10_FRESH_PILOT_ERROR: " + str(exc)[:260], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
