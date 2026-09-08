#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import verify_build as core


def die(message: str) -> None:
    raise SystemExit(f"variant verify: {message}")


def artifact_set(directory: Path) -> dict[str, Path]:
    return {ext[1:]: core.single_artifact(directory, ext) for ext in (".gbl", ".hex", ".out")}


def section_snapshot(path: Path) -> dict[str, int | None]:
    s = core.readelf_sections(path)
    return {name: s.get(name) for name in (".text", ".data", ".bss", ".memory_manager_heap")}


def artifact_record(path: Path) -> dict[str, object]:
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": core.sha256(path)}


def canonical_sha256(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p009-dir", type=Path, required=True)
    ap.add_argument("--p011-dir", type=Path, required=True)
    ap.add_argument("--p013-dir", type=Path, required=True)
    ap.add_argument("--p009-slcp", type=Path, required=True)
    ap.add_argument("--p011-slcp", type=Path, required=True)
    ap.add_argument("--p013-slcp", type=Path, required=True)
    ap.add_argument("--p011-identity-json", type=Path, required=True)
    ap.add_argument("--source-commit", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        die("source commit must be full SHA1")

    p009_profile = core.profile(args.p009_slcp)
    p011_profile = core.profile(args.p011_slcp)
    p013_profile = core.profile(args.p013_slcp)
    core.validate_profile(p009_profile, core.P009_ONLY)
    if p011_profile != p009_profile:
        die("P011 changed Zigbee/transport resource values relative to frozen P009")
    expected_p013 = dict(p009_profile)
    expected_p013["SL_ZIGBEE_MULTICAST_TABLE_SIZE"] = 32
    if p013_profile != expected_p013:
        diff = {k: (expected_p013.get(k), p013_profile.get(k)) for k in sorted(set(expected_p013) | set(p013_profile)) if expected_p013.get(k) != p013_profile.get(k)}
        die(f"P013 must differ from P009 only by multicast26->32: {diff}")

    p009 = artifact_set(args.p009_dir)
    p011 = artifact_set(args.p011_dir)
    p013 = artifact_set(args.p013_dir)
    if core.sha256(p011["gbl"]) == core.sha256(p009["gbl"]):
        die("P011 GBL is unexpectedly identical to P009")
    if core.sha256(p013["gbl"]) == core.sha256(p009["gbl"]):
        die("P013 GBL is unexpectedly identical to P009")

    sec009 = section_snapshot(p009["out"])
    sec011 = section_snapshot(p011["out"])
    sec013 = section_snapshot(p013["out"])
    if sec009[".bss"] != 22_988 or sec009[".memory_manager_heap"] != 229_896:
        die(f"P009 linked baseline drifted: {sec009}")
    if sec013[".bss"] != 23_012 or sec013[".memory_manager_heap"] != 229_896:
        die(f"P013 linked multicast contract drifted: {sec013}")
    if sec013[".bss"] - sec009[".bss"] != 24:
        die("P013 must add exactly 24 B .bss over P009")
    if sec011[".memory_manager_heap"] != 229_896:
        die(f"P011 changed memory-manager reservation: {sec011}")
    if not isinstance(sec011[".bss"], int) or sec011[".bss"] - sec009[".bss"] > 2048:
        die(f"P011 .bss growth is unexpectedly large: P009={sec009['.bss']} P011={sec011['.bss']}")
    if isinstance(sec009[".text"], int) and isinstance(sec011[".text"], int) and sec011[".text"] - sec009[".text"] > 32768:
        die(f"P011 .text growth exceeds 32 KiB guardrail: {sec011['.text'] - sec009['.text']}")

    sy009 = core.readelf_symbols(p009["out"])
    sy011 = core.readelf_symbols(p011["out"])
    sy013 = core.readelf_symbols(p013["out"])
    for name, size in {
        "rx_buffer_vcom": 512,
        "sli_zigbee_broadcast_table_data": 512,
        "sli_zigbee_incoming_aps_frame_counters": 52,
        "sli_zigbee_multicast_table": 104,
    }.items():
        if sy009.get(name) != size or sy011.get(name) != size:
            die(f"P011 did not preserve P009 linked resource {name}={size}")
    if sy013.get("sli_zigbee_multicast_table") != 128:
        die("P013 multicast backing array is not 128 B")
    xncp_symbols = (
        "sl_zigbee_af_xncp_get_xncp_information_cb",
        "sl_zigbee_af_xncp_incoming_custom_frame_cb",
    )
    missing = [name for name in xncp_symbols if not isinstance(sy011.get(name), int) or sy011.get(name, 0) <= 0]
    if missing:
        die(f"P011 linked ELF lacks expected XNCP callback symbols: {missing}")

    identity = json.loads(args.p011_identity_json.read_text(encoding="utf-8"))
    if identity.get("profile_id") != "P011-IDENTITY-ON-P009" or identity.get("source_commit") != args.source_commit:
        die("P011 identity record does not bind profile/full source commit")
    resource_profile = identity.get("resource_profile")
    if not isinstance(resource_profile, dict):
        die("P011 identity record lacks canonical resource profile")
    full_hash = canonical_sha256(resource_profile)
    if identity.get("canonical_resource_profile_sha256") != full_hash:
        die("P011 identity record canonical hash mismatch")
    if identity.get("wire_hash_prefix_hex") != full_hash[:32]:
        die("P011 wire hash prefix does not match canonical profile hash")
    if identity.get("wire_commit_prefix") != args.source_commit[:12]:
        die("P011 wire commit prefix mismatch")

    report = {
        "schema": 1,
        "source_commit": args.source_commit,
        "profiles": {
            "P009": {"id": "P009-RX512-BTT64-KEY12-MCAST26", "resource_profile": p009_profile, "sections": sec009, "artifacts": {k: artifact_record(v) for k, v in p009.items()}},
            "P011": {"id": "P011-IDENTITY-ON-P009", "resource_profile": p011_profile, "sections": sec011, "delta_vs_p009": {k: (sec011[k] - sec009[k]) if isinstance(sec011[k], int) and isinstance(sec009[k], int) else None for k in sec009}, "artifacts": {k: artifact_record(v) for k, v in p011.items()}, "identity": identity},
            "P013": {"id": "P013-P009-MCAST32", "resource_profile": p013_profile, "sections": sec013, "delta_vs_p009": {k: (sec013[k] - sec009[k]) if isinstance(sec013[k], int) and isinstance(sec009[k], int) else None for k in sec009}, "artifacts": {k: artifact_record(v) for k, v in p013.items()}},
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
