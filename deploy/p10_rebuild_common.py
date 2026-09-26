"""Shared fail-closed helpers for P10 rebuild/cutover tooling."""
from __future__ import annotations

import hashlib
import json
import shlex
import stat
import time
import uuid
import zipfile
from pathlib import Path

from p10_data_bundle import ADDON, REMOTE_ROOTS, addon_info
from p10_data_bundle import verify as verify_bundle

TRANSIENT_STATES = {"startup", "shutdown"}
QUIESCENT_STATES = {"stopped", "error"}


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def find_root(sftp) -> str:
    for root in REMOTE_ROOTS:
        try:
            info = sftp.lstat(root)
            if not stat.S_ISDIR(info.st_mode):
                continue
            with sftp.open(root + "/configuration.yaml", "rb"):
                return root
        except FileNotFoundError:
            continue
    raise RuntimeError("Cannot locate live Zigbee2MQTT data root")


def _container_running(client) -> bool:
    command = "docker ps --filter name=^/app_" + ADDON + "$ --format '{{.Names}}'"
    _, stdout, _ = client.exec_command(command, timeout=15)
    raw = stdout.read().decode("utf-8", errors="replace").strip()
    if stdout.channel.recv_exit_status() != 0:
        raise RuntimeError("Cannot verify Zigbee2MQTT container state")
    return bool(raw)


def _wait_supervisor(client, wanted: set[str], timeout_s: int) -> dict:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = addon_info(client)
        if last.get("state") in wanted:
            return last
        time.sleep(1)
    raise RuntimeError(
        "Timed out waiting for Zigbee2MQTT Supervisor state; last="
        + str(None if last is None else last.get("state"))
    )


def ensure_quiescent(client, timeout_s: int = 120) -> dict:
    """Stop exactly once, tolerate Supervisor transitional/duplicate-stop races."""
    state = addon_info(client).get("state")
    if state in TRANSIENT_STATES:
        try:
            _wait_supervisor(client, {"started"} | QUIESCENT_STATES, min(45, timeout_s))
        except RuntimeError:
            pass
        state = addon_info(client).get("state")

    if state not in QUIESCENT_STATES:
        _, stdout, _ = client.exec_command(
            "ha apps stop " + ADDON + " --no-progress --raw-json", timeout=None
        )
        stdout.channel.settimeout(None)
        stdout.read()
        # Command return code is not authoritative: Supervisor may already be
        # transitioning. The observed state/container below is authoritative.
        stdout.channel.recv_exit_status()

    info = _wait_supervisor(client, QUIESCENT_STATES, timeout_s)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not _container_running(client):
            return {
                "addon_quiescent": True,
                "supervisor_state": info.get("state"),
                "container_running": False,
            }
        time.sleep(1)
    raise RuntimeError("Supervisor is quiescent but Zigbee2MQTT container is still running")


def ensure_started(client, timeout_s: int = 150) -> dict:
    """Start at most once and treat an already-running startup as success-in-progress."""
    state = addon_info(client).get("state")
    if state == "started":
        if not _container_running(client):
            raise RuntimeError("Supervisor reports started but container is absent")
        return {"addon_started": True, "start_command_issued": False}

    if state == "startup":
        info = _wait_supervisor(client, {"started"} | QUIESCENT_STATES, timeout_s)
        if info.get("state") == "started" and _container_running(client):
            return {"addon_started": True, "start_command_issued": False}
        state = info.get("state")

    if state not in QUIESCENT_STATES:
        raise RuntimeError("Unexpected add-on state before start: " + str(state))

    _, stdout, _ = client.exec_command(
        "ha apps start " + ADDON + " --no-progress --raw-json", timeout=None
    )
    stdout.channel.settimeout(None)
    stdout.read()
    stdout.channel.recv_exit_status()  # observed state below is authoritative
    info = _wait_supervisor(client, {"started"} | QUIESCENT_STATES, timeout_s)
    if info.get("state") != "started":
        raise RuntimeError("Zigbee2MQTT returned to " + str(info.get("state")) + " during startup")
    if not _container_running(client):
        raise RuntimeError("Supervisor reports started but Zigbee2MQTT container is absent")
    return {"addon_started": True, "start_command_issued": True}


def atomic_replace(sftp, path: str, raw: bytes) -> None:
    """Atomic same-filesystem replace only. No remove-then-rename fallback."""
    temp = path + ".p10-tmp-" + uuid.uuid4().hex
    old_mode = None
    try:
        try:
            old_mode = stat.S_IMODE(sftp.lstat(path).st_mode)
        except FileNotFoundError:
            pass
        with sftp.open(temp, "wb") as stream:
            stream.write(raw)
            stream.flush()
        if old_mode is not None:
            sftp.chmod(temp, old_mode)
        try:
            sftp.posix_rename(temp, path)
        except (AttributeError, OSError) as exc:
            raise RuntimeError("Atomic POSIX rename is unavailable; refusing file replacement") from exc
    finally:
        try:
            sftp.remove(temp)
        except FileNotFoundError:
            pass


def remove_regular_if_present(sftp, path: str) -> None:
    try:
        mode = sftp.lstat(path).st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISREG(mode):
        raise RuntimeError("Refusing to remove non-regular path: " + path)
    sftp.remove(path)


def cold_bundle_material(bundle: Path) -> dict:
    checked = verify_bundle(bundle)
    if checked.get("cold_consistent") is not True:
        raise RuntimeError("Verified COLD bundle required")
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        required = {
            "data/configuration.yaml",
            "data/database.db",
            "data/coordinator_backup.json",
            "meta/addon_options.private.json",
            "meta/manifest.private.json",
        }
        if not required <= names:
            raise RuntimeError("Cold bundle is missing required recovery material")
        addon_wrapper = json.loads(archive.read("meta/addon_options.private.json"))
        options = addon_wrapper.get("options")
        if not isinstance(options, dict):
            raise TypeError("Cold bundle add-on options are malformed")
        cfg_raw = archive.read("data/configuration.yaml")
        backup = json.loads(archive.read("data/coordinator_backup.json"))
        if not isinstance(backup, dict):
            raise TypeError("Cold coordinator backup is malformed")
        data_files = {
            name.removeprefix("data/"): archive.read(name)
            for name in names
            if name.startswith("data/") and not name.endswith("/")
        }
        return {
            "verified": checked,
            "configuration_raw": cfg_raw,
            "coordinator_backup": backup,
            "addon_options": options,
            "data_files": data_files,
            "bundle_sha256": sha256_file(bundle),
        }


SUPERVISOR_OPTIONS_REMOTE = r"""
import json, os, sys, urllib.request
payload=json.load(sys.stdin)
slug=payload["slug"]
headers={"Authorization":"Bearer "+os.environ["SUPERVISOR_TOKEN"],
         "Content-Type":"application/json"}
base="http://supervisor/addons/"+slug

def request(method,suffix,data=None):
    raw=None if data is None else json.dumps(data,sort_keys=True).encode()
    req=urllib.request.Request(base+suffix,data=raw,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=30) as response:
        body=json.loads(response.read().decode())
    if body.get("result")!="ok":
        raise RuntimeError("Supervisor request failed")
    return body.get("data")

info=request("GET","/info")
if info.get("options")!=payload["expected"]:
    raise RuntimeError("Live add-on options differ from expected precondition")
if payload["expected"]!=payload["new"]:
    request("POST","/options",{"options":payload["new"]})
after=request("GET","/info")
if after.get("options")!=payload["new"]:
    raise RuntimeError("Add-on options did not converge")
print(json.dumps({"ok":True,"changed":payload["expected"]!=payload["new"]}))
"""


def replace_addon_options(client, expected: dict, new: dict) -> dict:
    """Compare-and-swap add-on options through Supervisor; secrets never printed."""
    command = "python3 -c " + shlex.quote(SUPERVISOR_OPTIONS_REMOTE)
    stdin, stdout, _ = client.exec_command(command, timeout=None)
    stdin.channel.settimeout(None)
    stdout.channel.settimeout(None)
    stdin.write(json.dumps({"slug": ADDON, "expected": expected, "new": new}, sort_keys=True))
    stdin.channel.shutdown_write()
    raw = stdout.read().decode("utf-8", errors="replace").strip()
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        raise RuntimeError("Supervisor add-on options compare-and-swap failed")
    data = json.loads(raw)
    if data.get("ok") is not True:
        raise RuntimeError("Supervisor did not confirm add-on options update")
    return {"options_restored": True, "options_changed": bool(data.get("changed"))}


def backup_network_fingerprint(backup: dict) -> str:
    """Secret-free identity fingerprint. Deliberately excludes network key."""
    payload = {
        "coordinator_ieee": str(backup.get("coordinator_ieee") or "").lower(),
        "pan_id": str(backup.get("pan_id") or "").lower(),
        "extended_pan_id": str(backup.get("extended_pan_id") or "").lower(),
        "channel": backup.get("channel"),
    }
    if not payload["coordinator_ieee"] or not payload["pan_id"] or not payload["extended_pan_id"]:
        raise ValueError("Coordinator backup lacks network identity fields")
    return sha256_bytes(json.dumps(payload, sort_keys=True).encode())


def backup_device_ieees(backup: dict) -> set[str]:
    result = set()
    for item in backup.get("devices") or []:
        if not isinstance(item, dict):
            continue
        raw = item.get("ieee_address")
        if isinstance(raw, str):
            result.add(raw.lower().removeprefix("0x"))
    return result


def restore_all_data_files(sftp, root: str, material: dict) -> dict:
    count = 0
    for relative, raw in sorted(material["data_files"].items()):
        # The cold bundle capture is already path-validated. Create parent
        # directories only when they are part of the captured application tree.
        parts = relative.split("/")
        current = root
        for part in parts[:-1]:
            current += "/" + part
            try:
                mode = sftp.lstat(current).st_mode
                if not stat.S_ISDIR(mode):
                    raise RuntimeError("Rollback parent path is not a directory")
            except FileNotFoundError:
                sftp.mkdir(current)
        atomic_replace(sftp, root + "/" + relative, raw)
        count += 1
    return {"restored_application_files": count}
