"""Fail-safe fresh-network pilot cutover for MR4U CC2674P10 / Z-Stack.

The tool preserves converter/tuning files and replaces only active Zigbee2MQTT
network/application state. It requires a verified cold bundle and can restore
that exact pre-pilot state. It never flashes coordinator firmware.

Default is dry-run. Live cutover requires the exact approval phrase.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import stat
import sys
import time
import uuid
import zipfile
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p10_data_bundle import load_ha, addon_info, verify as verify_bundle, REMOTE_ROOTS, ADDON

VERSION = "0.1.0"
CUTOVER_APPROVAL = "FORM_FRESH_P10_PILOT_NETWORK"
ROLLBACK_APPROVAL = "RESTORE_PRE_PILOT_P10_COLD_STATE"
PILOT_BASE_TOPIC = "zigbee2mqtt_p10_pilot"
ACTIVE_STATE = ("database.db", "database.db.backup", "coordinator_backup.json", "state.json")
RESTORE_FILES = ("configuration.yaml",) + ACTIVE_STATE


def sha256(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            d.update(chunk)
    return d.hexdigest()


def cold_material(bundle: Path) -> dict:
    checked = verify_bundle(bundle)
    if checked.get("cold_consistent") is not True:
        raise RuntimeError("Verified cold bundle required")
    with zipfile.ZipFile(bundle) as z:
        names = set(z.namelist())
        missing = {"data/" + n for n in RESTORE_FILES} - names
        if missing:
            raise RuntimeError("Cold bundle missing rollback files")
        cfg_raw = z.read("data/configuration.yaml")
        cfg = yaml.safe_load(cfg_raw)
        if not isinstance(cfg, dict):
            raise ValueError("Cold configuration is invalid")
        old_advanced = cfg.get("advanced") or {}
        if not isinstance(old_advanced, dict):
            raise ValueError("Cold advanced config invalid")
        return {
            "verified": checked,
            "configuration_raw": cfg_raw,
            "configuration": cfg,
            "old_identity": {
                "pan_id": old_advanced.get("pan_id"),
                "ext_pan_id": old_advanced.get("ext_pan_id"),
                "network_key": old_advanced.get("network_key"),
                "channel": old_advanced.get("channel", cfg.get("channel", 11)),
            },
        }


def find_root(sftp) -> str:
    for root in REMOTE_ROOTS:
        try:
            if stat.S_ISDIR(sftp.stat(root).st_mode):
                with sftp.open(root + "/configuration.yaml", "rb"):
                    return root
        except FileNotFoundError:
            pass
    raise RuntimeError("Cannot locate live Zigbee2MQTT data root")


def supervisor_stop(client) -> dict:
    info = addon_info(client)
    if info.get("state") != "started":
        raise RuntimeError("Expected Zigbee2MQTT started before cutover")
    _, out, _ = client.exec_command("ha apps stop " + ADDON + " --no-progress --raw-json", timeout=None)
    out.channel.settimeout(None)
    out.read()
    out.channel.recv_exit_status()
    for _ in range(45):
        info = addon_info(client)
        if info.get("state") in ("stopped", "error"):
            cmd = "docker ps --filter name=^/app_" + ADDON + "$ --format '{{.Names}}'"
            _, check, _ = client.exec_command(cmd, timeout=15)
            running = check.read().decode("utf-8", errors="replace").strip()
            if check.channel.recv_exit_status() == 0 and not running:
                return {"supervisor_state": info.get("state"), "container_running": False}
        time.sleep(1)
    raise RuntimeError("Zigbee2MQTT did not become quiescent")


def supervisor_start(client) -> None:
    _, out, _ = client.exec_command("ha apps start " + ADDON + " --no-progress --raw-json", timeout=None)
    out.channel.settimeout(None)
    out.read()
    if out.channel.recv_exit_status() != 0:
        raise RuntimeError("Supervisor refused Zigbee2MQTT start")
    for _ in range(75):
        if addon_info(client).get("state") == "started":
            return
        time.sleep(1)
    raise RuntimeError("Zigbee2MQTT did not reach started state")


def atomic_write(sftp, path: str, raw: bytes) -> None:
    temp = path + ".pilot-tmp-" + uuid.uuid4().hex
    try:
        with sftp.open(temp, "wb") as f:
            f.write(raw)
        try:
            sftp.posix_rename(temp, path)
        except (AttributeError, OSError):
            try:
                sftp.remove(path)
            except FileNotFoundError:
                pass
            sftp.rename(temp, path)
    finally:
        try:
            sftp.remove(temp)
        except FileNotFoundError:
            pass


def remove_if_present(sftp, path: str) -> None:
    try:
        mode = sftp.lstat(path).st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISREG(mode):
        raise RuntimeError("Refusing to remove non-regular active state path")
    sftp.remove(path)


def pilot_config(source: dict) -> dict:
    cfg = json.loads(json.dumps(source))
    serial = cfg.get("serial")
    if not isinstance(serial, dict) or serial.get("adapter") != "zstack":
        raise ValueError("Live configuration is not P10/Z-Stack")
    if not str(serial.get("port", "")).startswith("/dev/serial/by-id/"):
        raise ValueError("Pilot requires stable by-id serial path")

    cfg.pop("devices", None)
    cfg.pop("groups", None)
    home = cfg.get("homeassistant")
    if isinstance(home, dict):
        home["enabled"] = False
    else:
        cfg["homeassistant"] = {"enabled": False}

    mqtt = cfg.setdefault("mqtt", {})
    if not isinstance(mqtt, dict):
        raise ValueError("MQTT configuration invalid")
    mqtt["base_topic"] = PILOT_BASE_TOPIC

    advanced = cfg.setdefault("advanced", {})
    if not isinstance(advanced, dict):
        raise ValueError("Advanced configuration invalid")
    advanced["channel"] = 11
    advanced["network_key"] = "GENERATE"
    advanced["pan_id"] = "GENERATE"
    advanced["ext_pan_id"] = "GENERATE"
    advanced["log_level"] = "debug"
    return cfg


def read_live_config(sftp, root: str) -> tuple[bytes, dict]:
    with sftp.open(root + "/configuration.yaml", "rb") as f:
        raw = f.read(4 * 1024 * 1024)
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Live configuration invalid")
    return raw, parsed


def restore_from_bundle(client, bundle: Path, restart: bool) -> dict:
    supervisor_stop(client) if addon_info(client).get("state") == "started" else None
    sftp = client.open_sftp()
    root = find_root(sftp)
    with zipfile.ZipFile(bundle) as z:
        for name in RESTORE_FILES:
            atomic_write(sftp, root + "/" + name, z.read("data/" + name))
    if restart:
        supervisor_start(client)
    return {"restored_files": list(RESTORE_FILES), "restarted": restart}


def verify_fresh(client, old_identity: dict) -> dict:
    sftp = client.open_sftp()
    root = find_root(sftp)
    _, cfg = read_live_config(sftp, root)
    mqtt = cfg.get("mqtt") or {}
    home = cfg.get("homeassistant") or {}
    advanced = cfg.get("advanced") or {}

    if mqtt.get("base_topic") != PILOT_BASE_TOPIC:
        raise RuntimeError("Pilot MQTT base topic not active")
    if not isinstance(home, dict) or home.get("enabled") is not False:
        raise RuntimeError("Home Assistant discovery is not disabled")
    if advanced.get("channel") != 11:
        raise RuntimeError("Pilot channel is not 11")
    if any(advanced.get(k) == "GENERATE" for k in ("network_key", "pan_id", "ext_pan_id")):
        raise RuntimeError("Zigbee2MQTT did not materialize generated network identity")
    if advanced.get("network_key") == old_identity.get("network_key"):
        raise RuntimeError("Fresh pilot unexpectedly retained old network key")
    if advanced.get("ext_pan_id") == old_identity.get("ext_pan_id"):
        raise RuntimeError("Fresh pilot unexpectedly retained old extended PAN ID")

    ordinary = 0
    with sftp.open(root + "/database.db", "rb") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("type") not in ("Coordinator", "Group"):
                ordinary += 1
    if ordinary:
        raise RuntimeError("Fresh pilot database already contains ordinary devices")

    with sftp.open(root + "/coordinator_backup.json", "rb") as f:
        backup = json.loads(f.read().decode("utf-8"))
    if backup.get("channel") != 11:
        raise RuntimeError("Fresh coordinator backup is not on channel 11")
    return {
        "fresh_network_verified": True,
        "ordinary_device_records": ordinary,
        "mqtt_base_topic": PILOT_BASE_TOPIC,
        "homeassistant_discovery": False,
        "channel": 11,
        "network_identity_changed": True,
    }


def preflight(bundle: Path, expected_sha256: str) -> dict:
    if sha256(bundle) != expected_sha256:
        raise RuntimeError("Cold bundle SHA-256 mismatch")
    material = cold_material(bundle)
    client = load_ha()
    try:
        info = addon_info(client)
        sftp = client.open_sftp()
        root = find_root(sftp)
        live_raw, live_cfg = read_live_config(sftp, root)
        if hashlib.sha256(live_raw).hexdigest() != hashlib.sha256(material["configuration_raw"]).hexdigest():
            raise RuntimeError("Live configuration differs from cold rollback point")
        staged = pilot_config(live_cfg)
        return {
            "tool_version": VERSION,
            "cold_bundle_verified": True,
            "cold_bundle_sha256_match": True,
            "addon_state": info.get("state"),
            "data_root": root,
            "pilot_base_topic": PILOT_BASE_TOPIC,
            "pilot_channel": staged["advanced"]["channel"],
            "homeassistant_discovery_will_be_disabled": True,
            "active_state_files_to_remove": list(ACTIVE_STATE),
            "converter_and_stack_tuning_files_preserved": True,
            "production_changed": False,
        }
    finally:
        client.close()


def cutover(bundle: Path, expected_sha256: str, approval: str) -> dict:
    if approval != CUTOVER_APPROVAL:
        raise ValueError("Exact fresh-pilot approval phrase required")
    preflight(bundle, expected_sha256)
    material = cold_material(bundle)
    client = load_ha()
    changed = False
    try:
        supervisor_stop(client)
        sftp = client.open_sftp()
        root = find_root(sftp)
        live_raw, live_cfg = read_live_config(sftp, root)
        if hashlib.sha256(live_raw).hexdigest() != hashlib.sha256(material["configuration_raw"]).hexdigest():
            raise RuntimeError("Live config changed after stop; refusing cutover")
        cfg = pilot_config(live_cfg)
        pilot_raw = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True).encode("utf-8")
        atomic_write(sftp, root + "/configuration.yaml", pilot_raw)
        for name in ACTIVE_STATE:
            remove_if_present(sftp, root + "/" + name)
        changed = True
        supervisor_start(client)
        fresh = None
        last_error = None
        for _ in range(60):
            try:
                fresh = verify_fresh(client, material["old_identity"])
                break
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if addon_info(client).get("state") not in ("started",):
                    break
                time.sleep(1)
        if fresh is None:
            restore_from_bundle(client, bundle, restart=True)
            raise RuntimeError("Fresh P10 verification failed; cold state restored: " + str(last_error)[:140])
        return {
            "status": "FRESH_P10_PILOT_ACTIVE",
            "tool_version": VERSION,
            "cold_rollback_preserved": True,
            **fresh,
            "permit_join_opened": False,
        }
    except Exception:
        if changed and addon_info(client).get("state") != "started":
            try:
                restore_from_bundle(client, bundle, restart=True)
            except Exception:
                pass
        raise
    finally:
        client.close()


def rollback(bundle: Path, expected_sha256: str, approval: str) -> dict:
    if approval != ROLLBACK_APPROVAL:
        raise ValueError("Exact rollback approval phrase required")
    if sha256(bundle) != expected_sha256:
        raise RuntimeError("Cold bundle SHA-256 mismatch")
    cold_material(bundle)
    client = load_ha()
    try:
        result = restore_from_bundle(client, bundle, restart=True)
        return {"status": "PRE_PILOT_P10_STATE_RESTORED", **result}
    finally:
        client.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("preflight", "cutover", "rollback"):
        q = sub.add_parser(name)
        q.add_argument("--bundle", required=True, type=Path)
        q.add_argument("--sha256", required=True)
        q.add_argument("--approval", default="")
    args = p.parse_args(argv)
    try:
        if args.action == "preflight":
            result = preflight(args.bundle, args.sha256)
        elif args.action == "cutover":
            result = cutover(args.bundle, args.sha256, args.approval)
        else:
            result = rollback(args.bundle, args.sha256, args.approval)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError,
            json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print("P10_FRESH_PILOT_ERROR: " + str(exc)[:240], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
