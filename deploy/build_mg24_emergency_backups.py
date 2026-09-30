#!/usr/bin/env python3
"""Build fail-closed emergency MG24/Ember + future P10 rollback backups.

This tool never talks to hardware. It converts local backup files only.
Secrets remain in the generated private backup outputs; stdout/manifest are sanitized.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

LEASE_DEFAULT = 10_000_000
EXPECTED_P009_BYTES = 268_992
EXPECTED_P009_SHA256 = "a7747b396201d37da9073eaf81b599734684259debb78616b1fa3924fdac3fe8"
EXPECTED_ROLLBACK_BYTES = 268_896
EXPECTED_ROLLBACK_SHA256 = "b88a7786741dea5661a1299fd0f650c692ad6a00d8fbd0e76848de8a638daaef"

class PlanError(RuntimeError):
    pass

def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PlanError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PlanError(f"{path}: JSON root must be object")
    return value

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())

def verify_artifact(path: Path, expected_bytes: int, expected_sha256: str, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PlanError(f"{label}: missing artifact {path}")
    size = path.stat().st_size
    digest = sha256_file(path)
    if size != expected_bytes or digest != expected_sha256:
        raise PlanError(
            f"{label}: artifact mismatch bytes={size} sha256={digest}; "
            f"expected bytes={expected_bytes} sha256={expected_sha256}"
        )
    return {"name": path.name, "bytes": size, "sha256": digest}

def network_key_bytes(doc: dict[str, Any]) -> bytes:
    raw = (doc.get("network_key") or {}).get("key")
    if not isinstance(raw, str):
        raise PlanError("network_key.key missing/not hex string")
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise PlanError("network_key.key is not valid hex") from exc
    if len(key) != 16:
        raise PlanError(f"network_key.key must be 16 bytes, got {len(key)}")
    return key

def normalized_ieee(value: Any) -> str:
    if not isinstance(value, str):
        raise PlanError("coordinator_ieee missing")
    return value.lower().removeprefix("0x")

def identity(doc: dict[str, Any]) -> dict[str, Any]:
    nk = network_key_bytes(doc)
    return {
        "coordinator_ieee": normalized_ieee(doc.get("coordinator_ieee")),
        "pan_id": str(doc.get("pan_id")).lower().removeprefix("0x"),
        "extended_pan_id": str(doc.get("extended_pan_id")).lower().removeprefix("0x"),
        "channel": int(doc.get("channel")),
        "network_key_sha256": sha256_bytes(nk),
    }

def validate_common(doc: dict[str, Any], label: str) -> None:
    md = doc.get("metadata") or {}
    if md.get("format") != "zigpy/open-coordinator-backup" or md.get("version") != 1:
        raise PlanError(f"{label}: not OCB v1")
    ident = identity(doc)
    if not (11 <= ident["channel"] <= 26):
        raise PlanError(f"{label}: invalid Zigbee channel {ident['channel']}")
    fc = (doc.get("network_key") or {}).get("frame_counter")
    if not isinstance(fc, int) or fc < 0 or fc > 0xFFFFFFFF:
        raise PlanError(f"{label}: invalid frame counter {fc}")

def build(
    source: dict[str, Any],
    historical_ember: dict[str, Any],
    observed_floor: int,
    lease: int = LEASE_DEFAULT,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    validate_common(source, "source")
    validate_common(historical_ember, "historical ember")
    if "zstack" not in (source.get("stack_specific") or {}):
        raise PlanError("source must be Z-Stack backup")
    ember_specific = (historical_ember.get("stack_specific") or {}).get("ezsp")
    ember_internal = ((historical_ember.get("metadata") or {}).get("internal") or {})
    hashed_tclk = (ember_specific or {}).get("hashed_tclk")
    ezsp_version = ember_internal.get("ezspVersion")
    if not isinstance(hashed_tclk, str) or len(hashed_tclk) != 32:
        raise PlanError("historical Ember backup missing 16-byte hashed_tclk")
    if not isinstance(ezsp_version, int) or ezsp_version < 12:
        raise PlanError(f"historical Ember backup has unsupported ezspVersion={ezsp_version}")

    src_id = identity(source)
    hist_id = identity(historical_ember)
    mismatches = [k for k in src_id if src_id[k] != hist_id[k]]
    if mismatches:
        raise PlanError("historical Ember network identity mismatch: " + ", ".join(mismatches))

    src_fc = int(source["network_key"]["frame_counter"])
    if observed_floor < src_fc:
        observed_floor = src_fc
    if lease < 100_000:
        raise PlanError("counter lease must be at least 100000")
    ember_fc = observed_floor + lease
    p10_fc = ember_fc + lease
    if p10_fc > 0xFE000000:
        raise PlanError("planned counters too close to uint32 exhaustion")

    channel = src_id["channel"]

    ember = copy.deepcopy(source)
    ember["metadata"] = copy.deepcopy(source["metadata"])
    ember["metadata"]["source"] = "mg24-emergency-fallback-planner"
    ember["metadata"].setdefault("internal", {})
    ember["metadata"]["internal"].pop("znpVersion", None)
    ember["metadata"]["internal"]["ezspVersion"] = ezsp_version
    ember["stack_specific"] = {"ezsp": {"hashed_tclk": hashed_tclk}}
    ember["channel_mask"] = [channel]
    ember["network_key"]["frame_counter"] = ember_fc
    # Deliberate: this reproduces the network's long-running SONOFF Ember backup shape.
    # Do not stuff Z-Stack TCLK-seed-derived keys into Ember's small APP link-key table.
    ember["devices"] = []

    p10 = copy.deepcopy(source)
    p10["metadata"] = copy.deepcopy(source["metadata"])
    p10["metadata"]["source"] = "mg24-emergency-fallback-planner:p10-rollback"
    p10["channel_mask"] = [channel]
    p10["network_key"]["frame_counter"] = p10_fc

    if identity(ember) != src_id or identity(p10) != src_id:
        raise PlanError("internal error: network identity drift while building outputs")
    if p10.get("devices") != source.get("devices"):
        raise PlanError("internal error: P10 rollback device/security records changed")

    plan = {
        "schema": 1,
        "network_identity": src_id,
        "source_frame_counter": src_fc,
        "observed_counter_floor": observed_floor,
        "lease_size": lease,
        "ember_frame_counter": ember_fc,
        "p10_rollback_frame_counter": p10_fc,
        "source_device_records": len(source.get("devices") or []),
        "source_link_key_records": sum(
            1 for d in (source.get("devices") or [])
            if isinstance(d, dict) and isinstance(d.get("link_key"), dict) and d["link_key"].get("key")
        ),
        "ember_device_records": 0,
        "historical_ember_ezsp_version": ezsp_version,
        "historical_ember_hashed_tclk_sha256": sha256_bytes(bytes.fromhex(hashed_tclk)),
    }
    return ember, p10, plan

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-zstack-backup", type=Path, required=True)
    ap.add_argument("--p009-gbl", type=Path, required=True)
    ap.add_argument("--stock-rollback-gbl", type=Path, required=True)
    ap.add_argument("--historical-ember-backup", type=Path, required=True)
    ap.add_argument("--observed-counter-floor", type=int, required=True)
    ap.add_argument("--lease-size", type=int, default=LEASE_DEFAULT)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()

    p009_art = verify_artifact(args.p009_gbl, EXPECTED_P009_BYTES, EXPECTED_P009_SHA256, "P009")
    rollback_art = verify_artifact(args.stock_rollback_gbl, EXPECTED_ROLLBACK_BYTES, EXPECTED_ROLLBACK_SHA256, "stock rollback")
    source = load(args.source_zstack_backup)
    historical = load(args.historical_ember_backup)
    ember, p10, plan = build(source, historical, args.observed_counter_floor, args.lease_size)

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    ember_path = out / "coordinator_backup.ember-emergency.json"
    p10_path = out / "coordinator_backup.p10-future-rollback.json"
    manifest_path = out / "MANIFEST.sanitized.json"

    ember_path.write_text(json.dumps(ember, indent=2) + "\n", encoding="utf-8")
    p10_path.write_text(json.dumps(p10, indent=2) + "\n", encoding="utf-8")

    manifest = {
        **plan,
        "firmware": {
            "p009": p009_art,
            "matched_stock_rollback": rollback_art,
        },
        "inputs": {
            "source_zstack_backup_sha256": sha256_file(args.source_zstack_backup),
            "historical_ember_backup_sha256": sha256_file(args.historical_ember_backup),
        },
        "outputs": {
            "ember_backup": {"name": ember_path.name, "sha256": sha256_file(ember_path)},
            "p10_rollback_backup": {"name": p10_path.name, "sha256": sha256_file(p10_path)},
        },
        "warnings": [
            "Generated coordinator backup files contain Zigbee secrets and must stay private.",
            "Ember devices[] is intentionally empty to match this network's proven SONOFF Ember backup shape.",
            "Never run MG24 and P10 concurrently with the same coordinator IEEE/network identity.",
            "Take a fresh backup before every later coordinator transition; do not rewind counters.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
