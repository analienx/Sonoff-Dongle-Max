"""Offline Phase A evidence gate for an exact SMLIGHT P10 radio image.

No network, firmware, serial-port or backup writes. Manifest fields are claims
requiring independent review, not proof created by this program.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

BOARDS = ("SLZB-06P10", "SLZB-06P10U", "SLZB-MR4U")
REQUIRED = ("neighbor", "tclk", "link_keys", "children", "routing", "source_routes")
SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def verified_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    url = urlparse(value)
    return url.scheme == "https" and bool(url.hostname) and not url.username and not url.password


def verify_candidate(candidate: dict, *, target_board: str,
                     min_neighbor: int, min_tclk: int, actual_image_sha256: str | None = None) -> dict:
    """Check completeness of *declared* exact-image Phase A evidence only."""
    if not isinstance(candidate, dict):
        raise ValueError("Every candidate must be an object")
    item = {"name": str(candidate.get("name", "unnamed")), "status": "BLOCKED", "reasons": []}
    if candidate.get("board") != target_board:
        item["reasons"].append("Image board does not match the independently identified target board")
    if candidate.get("role") != "coordinator" or candidate.get("adapter") != "zstack":
        item["reasons"].append("Coordinator role and Z-Stack host protocol are not established")
    image = candidate.get("image")
    if not isinstance(image, dict):
        image = {}
    digest = image.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        item["reasons"].append("Exact local radio image SHA-256 missing/invalid")
        digest = None
    if actual_image_sha256 is None or digest is None or digest.lower() != actual_image_sha256.lower():
        item["reasons"].append("Radio image bytes not locally SHA-256 verified against this manifest")
    if not verified_url(image.get("vendor_source")):
        item["reasons"].append("HTTPS vendor source for this exact radio image missing")
    if not image.get("version") or not image.get("board_revision"):
        item["reasons"].append("Radio build identity or target board revision missing")
    capacities = candidate.get("capacities")
    if not isinstance(capacities, dict):
        capacities = {}
    for table in REQUIRED:
        entry = capacities.get(table)
        if not isinstance(entry, dict):
            entry = {}
        count = entry.get("entries")
        threshold = {"neighbor": min_neighbor, "tclk": min_tclk}.get(table, 1)
        if type(count) is not int or count < threshold:
            item["reasons"].append(f"{table}: missing, invalid or below provisional threshold {threshold}")
            continue
        evidence_hash = entry.get("image_sha256")
        if (entry.get("proof") != "exact-build" or
                not verified_url(entry.get("evidence_url")) or
                not digest or not isinstance(evidence_hash, str) or
                evidence_hash.lower() != digest.lower()):
            item["reasons"].append(f"{table}: exact-image source evidence and hash linkage missing")
    if not item["reasons"]:
        item["status"] = "MANIFEST_FIELDS_COMPLETE_UNVERIFIED"
    item["migration_test"] = candidate.get("migration", "not-tested")
    item["groupcast_test"] = "reported-pass" if candidate.get("groupcast_passed") is True else "not-proven"
    item["production_migration_authorized"] = False
    return item


def report(doc: dict, *, target_board: str, min_neighbor: int, min_tclk: int,
           actual_image_sha256: str | None = None) -> dict:
    if not isinstance(doc, dict) or not isinstance(doc.get("candidates"), list):
        raise ValueError("Expected {'candidates': [...]} JSON manifest")
    if target_board not in BOARDS or min_neighbor <= 26 or min_tclk < 1:
        raise ValueError("Invalid board or capacity thresholds")
    return {"purpose": "Phase A manifest completeness; NOT independently verified capacity",
            "target_board": target_board, "required_neighbor": min_neighbor,
            "required_tclk": min_tclk, "production_migration_authorized": False,
            "results": [verify_candidate(candidate, target_board=target_board,
                         min_neighbor=min_neighbor, min_tclk=min_tclk,
                         actual_image_sha256=actual_image_sha256)
                        for candidate in doc["candidates"]]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path, help="Public radio image metadata ONLY; never a coordinator backup")
    p.add_argument("--target-board", choices=BOARDS, required=True,
                   help="Physical model independently identified on the actual new unit")
    p.add_argument("--min-neighbor", type=int, default=60)
    p.add_argument("--min-tclk", type=int, default=100)
    p.add_argument("--out", type=Path, help="Create report without overwriting prior evidence")
    p.add_argument("--image", type=Path, help="Exact local radio image to hash and match with manifest")
    args = p.parse_args(argv)
    try:
        doc = json.loads(args.manifest.read_text(encoding="utf-8"))
        local_hash = None
        if args.image:
            with args.image.open("rb") as image_file:
                local_hash = hashlib.file_digest(image_file, "sha256").hexdigest()
        result = report(doc, target_board=args.target_board,
                        min_neighbor=args.min_neighbor, min_tclk=args.min_tclk,
                        actual_image_sha256=local_hash)
        if args.out:
            with args.out.open("x", encoding="utf-8") as output:
                json.dump(result, output, indent=2)
                output.write("\n")
        print(json.dumps(result, indent=2))
        # Even a self-declared complete manifest cannot make a migration gate green.
        return 4 if any(x["status"] == "MANIFEST_FIELDS_COMPLETE_UNVERIFIED"
                        for x in result["results"]) else 3
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"FIRMWARE_AUDIT_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
