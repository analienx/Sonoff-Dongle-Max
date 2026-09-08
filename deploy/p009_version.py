"""Structured, owner-bound coordinator-version proof for P009 deployment gates.

The normal Zigbee interface remains stock. This module enriches the existing
secret-safe snapshot with coordinator metadata and fixes the Zigbee2MQTT 2.14
health-check freshness proof without replacing the deployment state machine.
"""
from __future__ import annotations

import json
import re
import shlex

import p009_common

APPROVED_EMBER = (9, 1, 1)
APPROVED_EZSP = 19


def current_bridge_state_214(host: str, container: str) -> dict[str, object]:
    """Read bridge/info plus a fresh Zigbee2MQTT 2.14 health response.

    Zigbee2MQTT 2.14 health_check accepts an empty request and does not echo a
    transaction identifier. Subscribe first, publish the empty request, and
    accept only a non-retained healthy response received after publication. The
    exact Docker container id/start epoch remains the outer owner/freshness anchor.
    """
    js = r'''const fs=require("node:fs");
const mqtt=require("/app/node_modules/.pnpm/mqtt@5.15.2/node_modules/mqtt");
const YAML=require("/app/node_modules/.pnpm/js-yaml@5.4.1/node_modules/js-yaml");
const cfg=YAML.load(fs.readFileSync("/config/zigbee2mqtt/configuration.yaml","utf8"));
const base=(cfg.mqtt&&cfg.mqtt.base_topic)||"zigbee2mqtt";
const infoTopic=`${base}/bridge/info`,req=`${base}/bridge/request/health_check`,resp=`${base}/bridge/response/health_check`;
const c=mqtt.connect(cfg.mqtt.server,{username:cfg.mqtt?.user,password:cfg.mqtt?.password,reconnectPeriod:0});
let info=null,infoRetain=null,health=null,healthRetain=null,requestMs=null,responseMs=null,done=false;
function finish(code,msg){if(done)return;done=true;clearTimeout(timer);if(msg)console.error(msg);if(code===0)console.log(JSON.stringify({captured_ms:Date.now(),health_request_ms:requestMs,health_response_ms:responseMs,info_retain:infoRetain,health_retain:healthRetain,info,health}));c.end(true,{},()=>process.exit(code));}
function maybe(){if(info&&health&&requestMs!==null&&responseMs>=requestMs&&!healthRetain)finish(0);}
c.on("error",e=>finish(2,`MQTT error: ${e.message}`));
c.on("connect",()=>c.subscribe([infoTopic,resp],{qos:1},err=>{if(err)return finish(2,err.message);requestMs=Date.now();c.publish(req,"",{qos:1},err2=>{if(err2)finish(2,err2.message);});}));
c.on("message",(topic,raw,packet)=>{let v;try{v=JSON.parse(raw.toString());}catch(e){return finish(2,`malformed ${topic}: ${e.message}`);}if(topic===infoTopic){info=v;infoRetain=!!packet.retain;maybe();}else if(topic===resp){if(requestMs===null)return;health=v;healthRetain=!!packet.retain;responseMs=Date.now();maybe();}});
const timer=setTimeout(()=>finish(2,"timeout waiting for current bridge state/2.14 health response"),8000);'''
    q = shlex.quote
    raw = p009_common.remote_exec(host, f"docker exec {q(container)} node -e {q(js)}").strip()
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        p009_common.die(f"cannot parse current bridge state: {exc}; output={raw[:300]!r}")
    if not isinstance(doc, dict) or not isinstance(doc.get("info"), dict) or not isinstance(doc.get("health"), dict):
        p009_common.die("current bridge state did not contain both bridge/info and post-request health response")
    health = doc["health"]
    health_data = health.get("data") if isinstance(health, dict) else None
    if health.get("status") != "ok" or not isinstance(health_data, dict) or health_data.get("healthy") is not True:
        p009_common.die(f"current Z2M health-check response is not healthy: {health}")
    if doc.get("health_retain") is not False:
        p009_common.die("health-check response was retained; current response freshness is not proven")
    req_ms, resp_ms = doc.get("health_request_ms"), doc.get("health_response_ms")
    if not isinstance(req_ms, (int, float)) or not isinstance(resp_ms, (int, float)) or resp_ms < req_ms:
        p009_common.die("health-check response timing does not prove it arrived after the request")
    return doc


def read_bridge_coordinator(host: str, addon: str) -> dict[str, object]:
    """Read only secret-safe coordinator/version fields from retained bridge/info."""
    container = p009_common.require_single_z2m_owner(host, addon)
    js = r'''const fs=require("node:fs");
const mqtt=require("/app/node_modules/.pnpm/mqtt@5.15.2/node_modules/mqtt");
const YAML=require("/app/node_modules/.pnpm/js-yaml@5.4.1/node_modules/js-yaml");
const cfg=YAML.load(fs.readFileSync("/config/zigbee2mqtt/configuration.yaml","utf8"));
const base=(cfg.mqtt&&cfg.mqtt.base_topic)||"zigbee2mqtt";
const topic=`${base}/bridge/info`;
let done=false;
const c=mqtt.connect(cfg.mqtt.server,{username:cfg.mqtt?.user,password:cfg.mqtt?.password,reconnectPeriod:0});
function finish(code,obj){if(done)return;done=true;clearTimeout(timer);if(obj)console.log(JSON.stringify(obj));c.end(true,{},()=>process.exit(code));}
const timer=setTimeout(()=>finish(3,{error:"bridge/info timeout"}),7000);
c.on("error",e=>finish(2,{error:String(e.message||e).slice(0,160)}));
c.on("connect",()=>c.subscribe(topic,{qos:0},err=>{if(err)finish(2,{error:String(err.message||err).slice(0,160)});}));
c.on("message",(t,b)=>{if(t!==topic)return;let d;try{d=JSON.parse(b.toString());}catch(e){return finish(2,{error:`malformed bridge/info: ${e.message}`});}
const x=d.coordinator||{},m=x.meta||{};
finish(0,{type:x.type??null,ieee_address:x.ieee_address??x.ieeeAddress??null,meta:{revision:m.revision??null,majorrel:m.majorrel??null,minorrel:m.minorrel??null,maintrel:m.maintrel??null,product:m.product??null,transportrev:m.transportrev??null},zigbee2mqtt_version:d.version??null,zigbee_herdsman_version:d.zigbee_herdsman?.version??null});});'''
    q = shlex.quote
    raw = p009_common.remote_exec(host, f"docker exec {q(container)} node -e {q(js)}").strip()
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bridge/info coordinator metadata is not JSON: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("error"):
        raise RuntimeError(f"bridge/info coordinator metadata unavailable: {doc}")
    return doc


def enrich_snapshot(snap: dict[str, object], host: str, addon: str) -> dict[str, object]:
    coordinator = read_bridge_coordinator(host, addon)
    snap["coordinator"] = coordinator
    evidence = snap.get("identity_evidence")
    if isinstance(evidence, dict):
        evidence["bridge_coordinator"] = coordinator
        sources = evidence.get("identity_sources")
        if isinstance(sources, dict):
            sources["emberznet_version"] = "bridge/info.coordinator.meta from the same exact running Z2M owner"
            sources["ezsp_version"] = "coordinator_backup metadata, with current-start-epoch log fallback"
    return snap


def validate_approved_firmware(snap: dict[str, object], label: str = "snapshot") -> dict[str, object]:
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
        ember_source = "current-start-epoch-logs"
        if re.search(r"(?<!\d)9\.1\.1(?!\d)", logs):
            ember_tuple = APPROVED_EMBER
    if ember_tuple != APPROVED_EMBER:
        raise RuntimeError(f"{label}: approved EmberZNet 9.1.1 not proven (source={ember_source}, observed={ember_tuple})")

    identity = snap.get("identity") or {}
    ezsp = identity.get("ezsp_version") if isinstance(identity, dict) else None
    ezsp_source = "coordinator-backup"
    if isinstance(ezsp, str) and ezsp.isdigit():
        ezsp = int(ezsp)
    if ezsp != APPROVED_EZSP:
        ezsp_source = "current-start-epoch-logs"
        if re.search(r"\bEZSP\b[^\n]*\b19\b|transportrev[^0-9]*19", logs, re.IGNORECASE):
            ezsp = APPROVED_EZSP
    if ezsp != APPROVED_EZSP:
        raise RuntimeError(f"{label}: approved EZSP19 not proven (source={ezsp_source}, observed={ezsp!r})")

    ctype = str(coordinator.get("type") or "") if isinstance(coordinator, dict) else ""
    if ctype and "ember" not in ctype.lower():
        raise RuntimeError(f"{label}: coordinator type is not Ember: {ctype!r}")

    return {
        "emberznet": "9.1.1",
        "ember_source": ember_source,
        "ezsp": APPROVED_EZSP,
        "ezsp_source": ezsp_source,
        "coordinator_type": coordinator.get("type") if isinstance(coordinator, dict) else None,
        "coordinator_revision": meta.get("revision") if isinstance(meta, dict) else None,
    }


def install() -> None:
    """Patch only freshness/version proof hooks; leave the state machine intact."""
    import p009_deploy

    p009_common.current_bridge_state = current_bridge_state_214
    original_snapshot = p009_deploy.snapshot

    def snapshot_with_version(host: str, addon: str, z2m_dir: str) -> dict[str, object]:
        snap = original_snapshot(host, addon, z2m_dir)
        return enrich_snapshot(snap, host, addon)

    def require_current_stack_version(snap: dict[str, object], label: str) -> None:
        proof = validate_approved_firmware(snap, label)
        snap["stack_proof"] = proof

    p009_deploy.snapshot = snapshot_with_version
    p009_deploy.require_current_stack_version = require_current_stack_version
