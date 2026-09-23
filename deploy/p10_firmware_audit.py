"""Fail-closed, offline P10 firmware matrix. No credentials or network backups read."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

REQUIRED = ("neighbor", "tclk", "source_routes", "routing")


def verify_candidate(candidate: dict, *, min_neighbor: int, min_tclk: int) -> dict:
    """Only exact-build, source-backed capacity values qualify; otherwise BLOCKED."""
    item = {"name": candidate.get("name", "unnamed"), "status": "BLOCKED", "reasons": []}
    board = candidate.get("board")
    if board not in {"SLZB-06P10", "SLZB-06P10U"}:
        item["reasons"].append("No proof that this image targets the exact P10 board")
    if candidate.get("role") != "coordinator":
        item["reasons"].append("Not a coordinator image")
    if candidate.get("adapter") != "zstack":
        item["reasons"].append("Not a validated Z-Stack host-protocol image")
    capacities = candidate.get("capacities", {})
    for table in REQUIRED:
        value = capacities.get(table, {})
        if value.get("proof") != "exact-build" or not isinstance(value.get("entries"), int):
            item["reasons"].append(f"{table}: exact image build/config evidence missing")
        elif value["entries"] < ({"neighbor": min_neighbor, "tclk": min_tclk}.get(table, 1)):
            item["reasons"].append(f"{table}: allocated capacity below required threshold")
    image = candidate.get("image")
    if not isinstance(image, dict) or not image.get("sha256") or not image.get("vendor_source"):
        item["reasons"].append("Exact image hash and vendor source missing")
    if candidate.get("migration") != "verified-on-same-stack":
        item["reasons"].append("Migration including security frame counters not yet verified")
    if not candidate.get("groupcast_passed"):
        item["reasons"].append("Groupcast regression test not passed")
    if not item["reasons"]:
        item["status"] = "CANDIDATE_FOR_ISOLATED_VALIDATION"
    return item


def report(doc: dict, *, min_neighbor: int, min_tclk: int) -> dict:
    if not isinstance(doc.get("candidates"), list):
        raise ValueError("Expected {'candidates': [...]} JSON manifest")
    return {"purpose": "P10 image evidence gate; never an automatic flash recommendation",
            "required_neighbor": min_neighbor, "required_tclk": min_tclk,
            "results": [verify_candidate(x, min_neighbor=min_neighbor, min_tclk=min_tclk)
                        for x in doc["candidates"]]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path, help="Public firmware evidence JSON only; NEVER a coordinator backup")
    p.add_argument("--min-neighbor", type=int, default=50)
    p.add_argument("--min-tclk", type=int, default=100)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    try:
        if args.min_neighbor < 26 or args.min_tclk < 1:
            raise ValueError("Invalid table thresholds")
        doc = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = report(doc, min_neighbor=args.min_neighbor, min_tclk=args.min_tclk)
        if args.out:
            with args.out.open("x", encoding="utf-8") as output:
                json.dump(result, output, indent=2)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"FIRMWARE_AUDIT_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
