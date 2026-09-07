"""Shared P009 safety helpers and configurable remote transport."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_HOST = "ha"
DEFAULT_ADDON = "45df7312_zigbee2mqtt"
DEFAULT_Z2M_DIR = "/config/zigbee2mqtt"
DEFAULT_REMOTE_TEMPLATE = os.environ.get("P009_REMOTE_TEMPLATE", "ssh {host} {command}")
BUILDER_PIN = "858c34b0eb6f53a2e0c89455ea489ceaa62d58db"
_REMOTE_TEMPLATE = DEFAULT_REMOTE_TEMPLATE


def die(message: str, code: int = 2) -> None:
    print(f"P009: FAIL: {message}", file=__import__("sys").stderr)
    raise SystemExit(code)


def run(cmd: list[str], *, capture: bool = True, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, input=input_text, capture_output=capture, check=check)


def configure_remote(template: str) -> None:
    global _REMOTE_TEMPLATE
    tokens = shlex.split(template)
    if not tokens:
        die("remote template is empty")
    if not any("{host}" in t for t in tokens) or not any("{command}" in t for t in tokens):
        die("remote template must contain both {host} and {command}")
    _REMOTE_TEMPLATE = template


def remote_argv(host: str, command: str) -> list[str]:
    tokens = shlex.split(_REMOTE_TEMPLATE)
    return [token.replace("{host}", host).replace("{command}", command) for token in tokens]


def remote_exec(host: str, command: str, *, input_text: str | None = None) -> str:
    return run(remote_argv(host, command), input_text=input_text).stdout


def remote_write_text(host: str, remote_path: str, content: str) -> None:
    remote_exec(host, f"umask 077; cat > {shlex.quote(remote_path)}", input_text=content)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def utcstamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_identity_from_backup_doc(doc: dict[str, object]) -> dict[str, object]:
    network_key = doc.get("network_key") or {}
    if not isinstance(network_key, dict):
        die("coordinator backup network_key is malformed")
    key_hex = network_key.get("key")
    if not isinstance(key_hex, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", key_hex):
        die("coordinator backup has no valid 16-byte network_key.key")
    devices = doc.get("devices")
    metadata = doc.get("metadata") or {}
    internal = metadata.get("internal") if isinstance(metadata, dict) else {}
    return {
        "coordinator_ieee": doc.get("coordinator_ieee"),
        "pan_id": doc.get("pan_id"),
        "extended_pan_id": doc.get("extended_pan_id"),
        "channel": doc.get("channel"),
        "network_key_sha256": sha256_bytes(bytes.fromhex(key_hex)),
        "network_key_sequence_number": network_key.get("sequence_number"),
        "device_backup_entries": len(devices) if isinstance(devices, list) else None,
        "backup_format": metadata.get("format") if isinstance(metadata, dict) else None,
        "backup_source": metadata.get("source") if isinstance(metadata, dict) else None,
        "ezsp_version": internal.get("ezspVersion") if isinstance(internal, dict) else None,
    }


def running_z2m_containers(host: str) -> list[str]:
    raw = remote_exec(host, "docker ps --format '{{.Names}}'")
    return [name.strip() for name in raw.splitlines() if "zigbee2mqtt" in name.lower()]


def expected_addon_container(addon: str) -> str:
    return addon if addon.startswith("addon_") else f"addon_{addon}"


def require_single_z2m_owner(host: str, addon: str | None = None) -> str:
    containers = running_z2m_containers(host)
    if len(containers) != 1:
        die(f"expected exactly one running Zigbee2MQTT container, found {containers}")
    container = containers[0]
    if addon is not None:
        expected = expected_addon_container(addon)
        if container != expected:
            die(f"running Zigbee2MQTT owner is {container!r}, expected exact HA add-on container {expected!r}")
    return container


def container_session(host: str, container: str) -> dict[str, object]:
    q = shlex.quote
    raw = remote_exec(host, f"docker inspect --format '{{{{json .State}}}}' {q(container)}").strip()
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"cannot parse Docker state for {container}: {exc}")
    if not isinstance(state, dict) or state.get("Running") is not True:
        die(f"expected running Docker state for {container}, got {state}")
    started = state.get("StartedAt")
    if not isinstance(started, str) or not started or started.startswith("0001-"):
        die(f"running container has no valid StartedAt: {started!r}")
    container_id = remote_exec(host, f"docker inspect --format '{{{{.Id}}}}' {q(container)}").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        die(f"unexpected Docker container id for {container}: {container_id!r}")
    return {"container": container, "container_id": container_id, "started_at": started}


def current_session_logs(host: str, container: str, started_at: str) -> str:
    q = shlex.quote
    # StartedAt comes from Docker itself; --since binds evidence to this container start epoch.
    return remote_exec(host, f"docker logs --since {q(started_at)} {q(container)} 2>&1")


def current_bridge_state(host: str, container: str) -> dict[str, object]:
    """Read bridge/info and prove the currently running Z2M process answers a health request.

    bridge/info is retained MQTT state, so its `retain` bit is recorded rather than hidden.
    Freshness is supplied by the correlated health-check response plus the Docker start epoch
    and current-session logs. No second adapter/NCP client is opened.
    """
    js = r'''const fs=require("node:fs");
const mqtt=require("/app/node_modules/.pnpm/mqtt@5.15.2/node_modules/mqtt");
const YAML=require("/app/node_modules/.pnpm/js-yaml@5.4.1/node_modules/js-yaml");
const cfg=YAML.load(fs.readFileSync("/config/zigbee2mqtt/configuration.yaml","utf8"));
const base=(cfg.mqtt&&cfg.mqtt.base_topic)||"zigbee2mqtt";
const infoTopic=`${base}/bridge/info`, req=`${base}/bridge/request/health_check`, resp=`${base}/bridge/response/health_check`;
const tx=`p009-health-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const c=mqtt.connect(cfg.mqtt.server,{username:cfg.mqtt?.user,password:cfg.mqtt?.password,reconnectPeriod:0});
let info=null,infoRetain=null,health=null,done=false;
function finish(code,msg){if(done)return;done=true;if(msg)console.error(msg);if(code===0)console.log(JSON.stringify({captured_ms:Date.now(),transaction:tx,info_retain:infoRetain,info,health}));c.end(true,{},()=>process.exit(code));}
function maybe(){if(info&&health)finish(0);}
c.on("error",e=>finish(2,`MQTT error: ${e.message}`));
c.on("connect",()=>c.subscribe([infoTopic,resp],{qos:1},err=>{if(err)return finish(2,err.message);c.publish(req,JSON.stringify({transaction:tx}),{qos:1},err2=>{if(err2)finish(2,err2.message);});}));
c.on("message",(topic,raw,packet)=>{let v;try{v=JSON.parse(raw.toString());}catch(e){return finish(2,`malformed ${topic}: ${e.message}`);}if(topic===infoTopic){info=v;infoRetain=!!packet.retain;maybe();}else if(topic===resp&&v.transaction===tx){health=v;maybe();}});
setTimeout(()=>finish(2,"timeout waiting for current bridge state/health response"),8000);'''
    q = shlex.quote
    raw = remote_exec(host, f"docker exec {q(container)} node -e {q(js)}").strip()
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"cannot parse current bridge state: {exc}; output={raw[:300]!r}")
    if not isinstance(doc, dict) or not isinstance(doc.get("info"), dict) or not isinstance(doc.get("health"), dict):
        die("current bridge state did not contain both bridge/info and correlated health response")
    if doc["health"].get("status") != "ok":
        die(f"current Z2M health-check response is not OK: {doc['health']}")
    return doc


def operational_identity_from_bridge_info(info: dict[str, object]) -> dict[str, object]:
    coordinator = info.get("coordinator") or {}
    network = info.get("network") or {}
    if not isinstance(coordinator, dict) or not isinstance(network, dict):
        die("bridge/info lacks coordinator/network objects")
    ieee = coordinator.get("ieee_address") or coordinator.get("ieeeAddress")
    pan = network.get("pan_id") if "pan_id" in network else network.get("panId")
    ext = network.get("extended_pan_id") if "extended_pan_id" in network else network.get("extendedPanId")
    channel = network.get("channel")
    out = {"coordinator_ieee": ieee, "pan_id": pan, "extended_pan_id": ext, "channel": channel}
    missing = [k for k, v in out.items() if v in (None, "", [])]
    if missing:
        die(f"current bridge/info network identity is incomplete: {missing}; network={network}; coordinator={coordinator}")
    return out


def _backup_identity_inside_container(host: str, container: str, z2m_dir: str) -> dict[str, object]:
    backup_path = f"{z2m_dir}/coordinator_backup.json"
    js = r'''const fs=require("node:fs"),crypto=require("node:crypto");
const p=process.argv[1],d=JSON.parse(fs.readFileSync(p,"utf8"));
const k=d.network_key&&d.network_key.key;
if(typeof k!=="string"||!/^[0-9a-fA-F]{32}$/.test(k)) throw new Error("invalid network key");
const m=d.metadata||{},i=m.internal||{},n=d.network_key||{};
const st=fs.statSync(p);
console.log(JSON.stringify({coordinator_ieee:d.coordinator_ieee,pan_id:d.pan_id,extended_pan_id:d.extended_pan_id,channel:d.channel,network_key_sha256:crypto.createHash("sha256").update(Buffer.from(k,"hex")).digest("hex"),network_key_sequence_number:n.sequence_number,device_backup_entries:Array.isArray(d.devices)?d.devices.length:null,backup_format:m.format,backup_source:m.source,ezsp_version:i.ezspVersion,backup_mtime_ms:st.mtimeMs,backup_bytes:st.size}));'''
    q = shlex.quote
    raw = remote_exec(host, f"docker exec {q(container)} node -e {q(js)} {q(backup_path)}").strip()
    try:
        identity = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"cannot parse safe coordinator backup identity: {exc}")
    if not isinstance(identity, dict):
        die("safe coordinator backup identity is not an object")
    return identity


def running_identity_evidence(host: str, addon: str, z2m_dir: str) -> tuple[dict[str, object], dict[str, object], str]:
    container = require_single_z2m_owner(host, addon)
    session = container_session(host, container)
    logs = current_session_logs(host, container, str(session["started_at"]))
    bridge = current_bridge_state(host, container)
    op = operational_identity_from_bridge_info(bridge["info"])
    backup = _backup_identity_inside_container(host, container, z2m_dir)
    # The live/current network fields come from the running owner. The key digest and
    # backup entry count intentionally remain labelled backup evidence.
    identity = {
        **op,
        "network_key_sha256": backup.get("network_key_sha256"),
        "network_key_sequence_number": backup.get("network_key_sequence_number"),
        "device_backup_entries": backup.get("device_backup_entries"),
        "backup_format": backup.get("backup_format"),
        "backup_source": backup.get("backup_source"),
        "ezsp_version": backup.get("ezsp_version"),
    }
    evidence = {
        "owner": session,
        "bridge_health_transaction": bridge.get("transaction"),
        "bridge_info_retain": bridge.get("info_retain"),
        "bridge_info_captured_ms": bridge.get("captured_ms"),
        "backup_mtime_ms": backup.get("backup_mtime_ms"),
        "backup_bytes": backup.get("backup_bytes"),
        "identity_sources": {
            "coordinator_ieee_pan_extpan_channel": "current running Z2M bridge/info",
            "network_key_sha256_sequence_device_entries": "coordinator_backup.json read inside current owner container",
        },
    }
    return identity, evidence, logs


def safe_identity_from_running_z2m(host: str, z2m_dir: str, addon: str = DEFAULT_ADDON) -> dict[str, object]:
    identity, _, _ = running_identity_evidence(host, addon, z2m_dir)
    return identity


def addon_info(host: str, addon: str) -> dict[str, object]:
    raw = remote_exec(host, f"ha addons info {shlex.quote(addon)} --raw-json")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"cannot parse add-on info: {exc}")
    if not isinstance(doc, dict):
        die("add-on info is not an object")
    return doc


def addon_state(info: dict[str, object]) -> str:
    for key in ("state", "status"):
        value = info.get(key)
        if isinstance(value, str):
            return value.lower()
    return "unknown"


def addon_logs(host: str, addon: str) -> str:
    return remote_exec(host, f"ha addons logs {shlex.quote(addon)}")


def appended_logs(before: str, after: str) -> tuple[str, bool]:
    if after.startswith(before):
        return after[len(before):], True
    return "\n".join(after.splitlines()[-500:]), False


def remote_hashes(host: str, z2m_dir: str) -> dict[str, str]:
    q = shlex.quote
    command = (
        "set -eu; "
        f"for f in {q(z2m_dir + '/configuration.yaml')} {q(z2m_dir + '/database.db')} {q(z2m_dir + '/coordinator_backup.json')}; do "
        'if [ -f "$f" ]; then sha256sum "$f"; fi; done'
    )
    out = remote_exec(host, command)
    result: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            result[Path(parts[1].lstrip("*")).name] = parts[0]
    return result


def version_lines_from_text(raw: str) -> list[str]:
    rx = re.compile(r"Zigbee2MQTT|zigbee-herdsman|EmberZNet|\bEZSP\b|Coordinator|\[P009 EZSP\]|\[STACK STATUS\]", re.IGNORECASE)
    return [line.strip()[:500] for line in raw.splitlines() if rx.search(line)][-150:]


def version_lines(host: str, addon: str) -> list[str]:
    container = require_single_z2m_owner(host, addon)
    sess = container_session(host, container)
    return version_lines_from_text(current_session_logs(host, container, str(sess["started_at"])))


def snapshot(host: str, addon: str, z2m_dir: str) -> dict[str, object]:
    info = addon_info(host, addon)
    identity, evidence, current_logs = running_identity_evidence(host, addon, z2m_dir)
    safe_addon = {k: info.get(k) for k in ("slug", "name", "version", "version_latest", "state", "status", "boot", "update_available") if k in info}
    return {
        "schema": 3,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "addon": safe_addon,
        "identity": identity,
        "identity_evidence": evidence,
        "remote_sha256": remote_hashes(host, z2m_dir),
        "version_lines": version_lines_from_text(current_logs),
    }


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, object]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read {path}: {exc}")
    if not isinstance(doc, dict):
        die(f"{path} is not a JSON object")
    return doc


def wait_state(host: str, addon: str, expected: set[str], timeout: int = 90) -> dict[str, object]:
    deadline = time.time() + timeout
    last: dict[str, object] = {}
    while time.time() < deadline:
        last = addon_info(host, addon)
        if addon_state(last) in expected:
            return last
        time.sleep(2)
    die(f"add-on state did not become {sorted(expected)}; last={addon_state(last)}")


def load_build_manifest(path: Path) -> dict[str, object]:
    doc = load_json(path)
    if doc.get("schema") != 2:
        die(f"build manifest schema must be 2 for hardened deployment, got {doc.get('schema')!r}")
    p009 = ((doc.get("p009") or {}).get("artifacts") or {}).get("gbl") or {}
    stock = ((doc.get("rollback_stock") or {}).get("artifacts") or {}).get("gbl") or {}
    if not isinstance(p009, dict) or not isinstance(stock, dict) or not p009.get("sha256") or not stock.get("sha256"):
        die("build manifest lacks P009/stock GBL hashes")
    if (doc.get("builder") or {}).get("commit") != BUILDER_PIN:
        die("build manifest builder pin is not the approved P009 pin")
    source_commit = (doc.get("source") or {}).get("repository_commit")
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        die("build manifest lacks exact source repository commit")
    fw = doc.get("firmware") or {}
    if fw.get("emberznet") != "9.1.1" or fw.get("ezsp") != 19:
        die(f"build manifest firmware mismatch: {fw}")
    p_profile = (doc.get("p009") or {}).get("profile") or {}
    s_profile = (doc.get("rollback_stock") or {}).get("profile") or {}
    required_p = {
        "SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE": 512,
        "SL_ZIGBEE_BROADCAST_TABLE_SIZE": 64,
        "SL_ZIGBEE_KEY_TABLE_SIZE": 12,
    }
    required_s = {
        "SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE": 128,
        "SL_ZIGBEE_BROADCAST_TABLE_SIZE": 30,
        "SL_ZIGBEE_KEY_TABLE_SIZE": 1,
    }
    if any(p_profile.get(k) != v for k, v in required_p.items()):
        die(f"build manifest does not describe approved P009 RX512/BTT64/key12: {p_profile}")
    if any(s_profile.get(k) != v for k, v in required_s.items()):
        die(f"build manifest does not describe stock rollback RX128/BTT30/key1: {s_profile}")
    allowed = set(doc.get("allowed_profile_differences") or [])
    if allowed != set(required_p):
        die(f"build manifest allowed profile differences are unexpected: {sorted(allowed)}")
    linked = doc.get("linked_evidence") or {}
    if not isinstance(linked, dict) or linked.get("validated") is not True:
        die("build manifest lacks successful linked-ELF evidence")
    return doc


def verify_bundle_checksums(bundle_root: Path) -> None:
    sums = bundle_root / "SHA256SUMS"
    if not sums.is_file():
        die(f"missing {sums}")
    for lineno, line in enumerate(sums.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            die(f"malformed SHA256SUMS line {lineno}")
        rel = parts[1].lstrip("*").removeprefix("./")
        path = bundle_root / rel
        if not path.is_file() or sha256_file(path) != parts[0]:
            die(f"bundle checksum mismatch: {rel}")


def validate_identity(identity: dict[str, object]) -> None:
    required = ("coordinator_ieee", "pan_id", "extended_pan_id", "channel", "network_key_sha256")
    missing = [k for k in required if identity.get(k) in (None, "", [])]
    if missing:
        die(f"coordinator identity is incomplete: {missing}")


def find_gbl(bundle_root: Path, manifest: dict[str, object], variant: str) -> Path:
    section = "p009" if variant == "p009" else "rollback_stock"
    rel_dir = "p009" if variant == "p009" else "rollback-stock"
    rec = (((manifest.get(section) or {}).get("artifacts") or {}).get("gbl") or {})
    path = bundle_root / rel_dir / str(rec.get("name"))
    if not path.is_file():
        die(f"{variant} GBL not found: {path}")
    actual = sha256_file(path)
    if actual != rec.get("sha256"):
        die(f"{variant} GBL SHA256 mismatch: expected {rec.get('sha256')} got {actual}")
    if rec.get("bytes") != path.stat().st_size:
        die(f"{variant} GBL size mismatch: manifest={rec.get('bytes')} actual={path.stat().st_size}")
    return path


def compare_identity(before: dict[str, object], after: dict[str, object]) -> list[str]:
    keys = ("coordinator_ieee", "pan_id", "extended_pan_id", "channel", "network_key_sha256", "network_key_sequence_number", "device_backup_entries")
    b = before["identity"]
    a = after["identity"]
    return [f"{k}: before={b.get(k)!r} after={a.get(k)!r}" for k in keys if b.get(k) != a.get(k)]


def repo_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None
