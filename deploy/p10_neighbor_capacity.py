"""Offline P10 neighbor-capacity evidence: macro dump or isolated Mgmt_Lqi pages.

Never opens a port, sends radio traffic, accesses production, or prints device IDs.
Neither mode establishes exact compiled capacity of the running radio by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

IEEE = re.compile(r"[a-fA-F0-9]{16}\Z")
DEFINE = re.compile(r"^\s*#\s*define\s+MAX_NEIGHBOR_ENTRIES\s+\(?\s*(\d+)[uU]?\s*\)?\s*$")


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def macro_report(path: Path, image: Path) -> dict:
    """Preprocessed -dM input only; a source header is NOT a compiled image."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if any(line.strip() and not re.match(r"^\s*#\s*define\s+", line) for line in lines):
        raise ValueError("Input is not a compiler-preprocessed -dM macro-only dump")
    matches = [DEFINE.fullmatch(line) for line in lines
               if re.match(r"^\s*#\s*define\s+MAX_NEIGHBOR_ENTRIES\b", line)]
    if len(matches) != 1 or matches[0] is None:
        raise ValueError("Need exactly one literal MAX_NEIGHBOR_ENTRIES definition in preprocessed macro dump")
    n = int(matches[0].group(1))
    if not 1 <= n <= 255:
        raise ValueError("Neighbor count outside supported evidence range")
    return {"source": "compiler-preprocessed-macro-dump", "configured_neighbor_entries_declared": n,
            "macro_dump_sha256": digest(path), "local_image_sha256": digest(image),
            "exact_running_image_link": "UNVERIFIED", "runtime_capacity": "UNKNOWN",
            "warning": "A macro dump and an image hash alone do not prove that this image was built with this setting."}


def integer(value: object, name: str, lower: int, upper: int) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"Invalid {name}")
    return value


def decode_capture(capture: dict) -> dict:
    """Require complete coherent pagination of a single coordinator table capture."""
    if not isinstance(capture, dict):
        raise ValueError("Capture must be an object")
    when = datetime.fromisoformat(capture["timestamp_utc"].replace("Z", "+00:00"))
    if when.utcoffset() is None:
        raise ValueError("Capture timestamp requires timezone")
    pages = capture.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("Missing Mgmt_Lqi pages")
    raw_modes = [isinstance(page, dict) and "znp_frame_hex" in page for page in pages]
    if any(raw_modes) and not all(raw_modes):
        raise ValueError("Cannot mix raw ZNP and manually decoded pages")
    cursor = 0
    expected_total = None
    seen = set()
    routers = set()
    for page in pages:
        if isinstance(page, dict) and "znp_frame_hex" in page:
            if len(page) != 1:
                raise ValueError("Raw frame page may contain only znp_frame_hex")
            page = decode_znp_mgmt_lqi(page["znp_frame_hex"])
        if not isinstance(page, dict) or type(page.get("status")) is not int or page["status"] != 0:
            raise ValueError("Unsuccessful or malformed Mgmt_Lqi response")
        total = integer(page.get("neighbor_table_entries"), "total", 0, 255)
        start = integer(page.get("start_index"), "start index", 0, 255)
        entries = page.get("entries")
        if not isinstance(entries, list):
            raise ValueError("Missing page entries")
        count = integer(page.get("neighbor_table_list_count"), "page count", 0, 255)
        if count != len(entries) or start != cursor or (expected_total is not None and total != expected_total):
            raise ValueError("Page gap, duplicate page, count mismatch or neighbor-table churn")
        if count == 0 and total > cursor:
            raise ValueError("Incomplete pagination: empty page before end")
        expected_total = total
        if cursor + count > total:
            raise ValueError("Page exceeds reported neighbor population")
        for record in entries:
            if not isinstance(record, dict) or not isinstance(record.get("ieee"), str):
                raise ValueError("Missing neighbor IEEE identifier in private input")
            address = record["ieee"].lower().replace(":", "").replace("-", "")
            if not IEEE.fullmatch(address) or address in ("0" * 16, "f" * 16) or address in seen:
                raise ValueError("Invalid or repeated neighbor identifier across pages")
            seen.add(address)
            device_type = integer(record.get("device_type"), "device type", 0, 3)
            rx = integer(record.get("rx_on_when_idle"), "RX-on-when-idle", 0, 3)
            integer(record.get("lqi"), "LQI", 0, 255)
            if device_type == 1 and rx == 1:
                routers.add(address)
        cursor += count
    if expected_total != cursor:
        raise ValueError("Incomplete pagination; not a full table snapshot")
    return {"timestamp": when, "total": cursor, "routers": routers,
            "all_pages_znp_fcs_checked": all(raw_modes)}


def snapshot_report(doc: dict, image: Path, minimum: int) -> dict:
    """Strict offline interpretation, not a radio acquisition or atomic snapshot."""
    integer(minimum, "target neighbor threshold", 27, 255)
    if not isinstance(doc, dict) or doc.get("scope") != "isolated-disposable-network":
        raise ValueError("Only explicitly isolated disposable-network captures are accepted")
    if doc.get("observer_role") != "coordinator" or doc.get("source") != "ZDO-Mgmt_Lqi_rsp":
        raise ValueError("Expected coordinator-sourced decoded Mgmt_Lqi responses")
    image_hash = digest(image)
    claimed_image_hash = doc.get("radio_image_sha256")
    if not isinstance(claimed_image_hash, str) or claimed_image_hash.lower() != image_hash:
        raise ValueError("Capture's radio image SHA-256 does not match supplied image file")
    captures = doc.get("captures")
    if not isinstance(captures, list) or not captures or len(captures) > 100:
        raise ValueError("Require 1 to 100 complete capture sequences")
    parsed = [decode_capture(x) for x in captures]
    timestamps = [x["timestamp"] for x in parsed]
    if timestamps != sorted(set(timestamps)):
        raise ValueError("Capture timestamps must be unique and chronological")
    maximum = max(len(x["routers"]) for x in parsed)
    stable = set.intersection(*(x["routers"] for x in parsed))
    return {"source": "offline-isolated-paginated-Mgmt_Lqi", "local_image_sha256": image_hash,
            "capture_count": len(parsed), "all_pages_znp_fcs_checked": all(x["all_pages_znp_fcs_checked"] for x in parsed),
            "observed_router_entries_peak": maximum,
            "observed_all_neighbor_entries_peak": max(x["total"] for x in parsed),
            "router_identifiers_present_in_all_captures": len(stable),
            "target_router_entries_in_complete_pagination": maximum >= minimum,
            "compiled_maximum": "UNKNOWN", "running_image_identity_verified": False,
            "isolation_and_collector_authenticity_independently_verified": False,
            "atomic_simultaneity_verified": False,
            "bidirectional_link_status_verified": False, "routing_reliability_verified": False,
            "production_migration_authorized": False,
            "warning": "Pages are collected sequentially: table churn can preserve totals and still alter membership. "
                       "Neither pagination nor stable identifiers prove an atomic 60-neighbor table, capacity ceiling, "
                       "Link Status, or successful unicast routing. Independent isolated stack instrumentation required."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    m = sub.add_parser("macro", help="Offline -dM preprocessed macros plus local image fingerprint")
    m.add_argument("macro_dump", type=Path)
    s = sub.add_parser("snapshot", help="Offline private isolated-network Mgmt_Lqi response pages")
    s.add_argument("private_capture", type=Path)
    s.add_argument("--min-neighbor", type=int, default=60)
    for p in (m, s):
        p.add_argument("--image", type=Path, required=True)
        p.add_argument("--out", type=Path, help="Exclusive non-identifying summary JSON")
    args = parser.parse_args(argv)
    try:
        result = (macro_report(args.macro_dump, args.image) if args.mode == "macro" else
                  snapshot_report(json.loads(args.private_capture.read_text(encoding="utf-8")),
                                  args.image, args.min_neighbor))
        if args.out:
            with args.out.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2, sort_keys=True)
                handle.write("\n")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print("NEIGHBOR_EVIDENCE_BLOCKED: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2


def decode_znp_mgmt_lqi(packet_hex: str) -> dict:
    """Decode an OFFLINE TI-ZNP ZDO_MGMT_LQI_RSP (0x45/B1) frame only.

    This does not send Mgmt_Lqi_req or open a transport. Every entry is a
    22-byte Zigbee neighbor descriptor; this response has 6-byte ZDO header.
    """
    if not isinstance(packet_hex, str) or not re.fullmatch(r"[0-9a-fA-F]+", packet_hex):
        raise ValueError("Expected complete hexadecimal ZNP response frame")
    wire = bytes.fromhex(packet_hex)
    if len(wire) < 11 or wire[0] != 0xFE or wire[2:4] != b"\x45\xb1":
        raise ValueError("Not a ZNP ZDO_MGMT_LQI_RSP frame")
    if len(wire) != wire[1] + 5:
        raise ValueError("Truncated or overlong ZNP frame")
    fcs = 0
    for byte in wire[1:]:
        fcs ^= byte
    if fcs:
        raise ValueError("Invalid ZNP frame checksum")
    payload = wire[4:-1]
    if len(payload) < 6 or payload[0:2] != b"\x00\x00":
        raise ValueError("Response source must be isolated coordinator NWK 0x0000")
    status, total, start, count = payload[2:6]
    if len(payload) != 6 + 22 * count:
        raise ValueError("ZDO neighbor descriptor length/count mismatch")
    entries = []
    for index in range(count):
        record = payload[6 + index * 22:6 + (index + 1) * 22]
        flags = record[18]
        entries.append({"ieee": record[8:16].hex(), "device_type": flags & 3,
                        "rx_on_when_idle": (flags >> 2) & 3, "lqi": record[21]})
    return {"status": status, "neighbor_table_entries": total,
            "start_index": start, "neighbor_table_list_count": count, "entries": entries}

if __name__ == "__main__":
    raise SystemExit(main())
