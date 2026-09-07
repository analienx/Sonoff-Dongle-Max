"""Structured coordinator-version proof for the P009 deployment gates.

The primary evidence is Zigbee2MQTT's retained bridge/info coordinator metadata
plus ezspVersion from the secret-safe coordinator backup identity.  Add-on logs
are retained only as a compatibility fallback when bridge/info lacks a version
tuple; they are not the preferred source of truth.
"""
from __future__ import annotations

import json
import re
import shlex

from p009_common import remote_exec, require_single_z2m_owner

APPROVED_EMBER = (9, 1, 1)
APPROVED_EZSP = 19


def read_bridge_coordinator(host: str) -> dict[str, object]:
    """Read one retained bridge/info message without exposing MQTT credentials."""
    container = require_single_z2m_owner(host)
    js = r'''const fs=require("node:fs");
const mqtt=require("/app/node_modules/.pnpm/mqtt@5.15.2/node_modules/mqtt");
const YAML=require("/app/node_modules/.pnpm/js-yaml@5.4.1/node_modules/js-yaml");
const cfg=YAML.load(fs.readFileSync("/config/zigbee2mqtt/configuration.yaml","utf8"));
const base=(cfg.mqtt&&cfg.mqtt.base_topic)||"zigbee2mqtt";
const topic=`${base}/bridge/info`;
let done=false;
function finish(code,obj){if(done)return;done=true;clearTimeout(timer);if(obj)console.log(JSON.stringify(obj));client.end(true,{},()=>process.exit(code));}
const client=mqtt.connect(cfg.mqtt.server,{username:cfg.mqtt?.user,password:cfg.mqtt?.password});
const timer=setTimeout(()=>finish(3,{error:"bridge/info timeout"}),7000);
client.on("error",e=>finish(2,{error:String(e.message||e).slice(0,160)}));
client.on("connect",()=>client.subscribe(topic,{qos:0},err=>{if(err)finish(2,{error:String(err.message||err).slice(0,160)});}));
client.on("message",(t,b)=>{if(t!==topic)return;let d;try{d=JSON.parse(b.toString());}catch{return;}const c=d.coordinator||{},m=c.meta||{};finish(0,{type:c.type??null,ieee_address:c.ieee_address??null,meta:{revision:m.revision??null,majorrel:m.majorrel??null,minorrel:m.minorrel??null,maintrel:m.maintrel??null,product:m.product??null,transportrev:m.transportrev??null},zigbee2mqtt_version:d.version??null,zigbee_herdsman_version:d.zigbee_herdsman?.version??null});});'''
    raw = remote_exec(host, f"docker exec {shlex.quote(container)} node -e {shlex.quote(js)}").strip()
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bridge/info coordinator metadata is not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise RuntimeError("bridge/info coordinator metadata is not an object")
    if doc.get("error"):
        raise RuntimeError(f"bridge/info coordinator metadata unavailable: {doc['error']}")
    return doc


def enrich_snapshot(snap: dict[str, object], host: str) -> dict[str, object]:
    """Attach secret-safe bridge metadata; preserve fallback evidence on failure."""
    try:
        snap["coordinator"] = {"available": True, **read_bridge_coordinator(host)}
    except Exception as exc:
        snap["coordinator"] = {"available": False, "error": str(exc)[:300]}
    return snap


def validate_approved_firmware(snap: dict[str, object]) -> dict[str, object]:
    """Require EmberZNet 9.1.1 and EZSP19, preferring structured evidence."""
    coordinator = snap.get("coordinator") or {}
    meta = coordinator.get("meta") if isinstance(coordinator, dict) else None
    logs = "\n".join(str(x) for x in (snap.get("version_lines") or []))

    ember_source = "bridge/info"
    ember_tuple: tuple[int, int, int] | None = None
    if isinstance(meta, dict):
        raw = (meta.get("majorrel"), meta.get("minorrel"), meta.get("maintrel"))
        if all(isinstance(v, int) and not isinstance(v, bool) for v in raw):
            ember_tuple = (int(raw[0]), int(raw[1]), int(raw[2]))
    if ember_tuple is None:
        ember_source = "logs-fallback"
        if re.search(r"(?<!\d)9\.1\.1(?!\d)", logs):
            ember_tuple = APPROVED_EMBER
    if ember_tuple != APPROVED_EMBER:
        raise RuntimeError(f"approved EmberZNet 9.1.1 not proven (source={ember_source}, observed={ember_tuple})")

    identity = snap.get("identity") or {}
    ezsp = identity.get("ezsp_version") if isinstance(identity, dict) else None
    ezsp_source = "coordinator-backup"
    if isinstance(ezsp, str) and ezsp.isdigit():
        ezsp = int(ezsp)
    if ezsp != APPROVED_EZSP:
        ezsp_source = "logs-fallback"
        if re.search(r"\bEZSP\b[^\n]*\b19\b", logs, re.IGNORECASE):
            ezsp = APPROVED_EZSP
    if ezsp != APPROVED_EZSP:
        raise RuntimeError(f"approved EZSP19 not proven (source={ezsp_source}, observed={ezsp!r})")

    return {
        "emberznet": "9.1.1",
        "ember_source": ember_source,
        "ezsp": APPROVED_EZSP,
        "ezsp_source": ezsp_source,
        "coordinator_type": coordinator.get("type") if isinstance(coordinator, dict) else None,
        "coordinator_revision": meta.get("revision") if isinstance(meta, dict) else None,
    }
