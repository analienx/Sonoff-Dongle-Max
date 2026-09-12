#!/usr/bin/env python3
"""Classify Zigbee2MQTT/Ember log failures for P013 coordinator evidence.

This tool is read-only. It separates hard coordinator/NCP regressions from
routing-repair churn so acceptance cannot hide address conflicts or resets,
while ordinary route repair is measured rather than treated as firmware proof.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

TIMESTAMP_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
NWK_RE = re.compile(r'(?:for|target["=: ]+)\s*["\']?(\d{1,5})')

HARD_PATTERNS = {
    "address_conflict": re.compile(r"ID conflict|ADDRESS_CONFLICT_SENT", re.I),
    "network_down": re.compile(r"network down|NETWORK_DOWN", re.I),
    "ncp_reset": re.compile(r"NCP.*reset|reset.*NCP|ASH.*reset", re.I),
    "ash_transport": re.compile(r"ASH_(?:OVERFLOW|FRAMING|OVERRUN)_ERROR", re.I),
    "packet_buffer": re.compile(r"ALLOCATE_PACKET_BUFFER_FAILURE", re.I),
    "phy_mac_queue": re.compile(r"PHY_TO_MAC_QUEUE_LIMIT_REACHED", re.I),
    "nwk_retry_overflow": re.compile(r"NWK_RETRY_OVERFLOW", re.I),
    "mac_no_ack": re.compile(r"MAC_NO_ACK", re.I),
    "aps_no_ack": re.compile(r"APS_NO_ACK", re.I),
}

ROUTE_PATTERNS = {
    "many_to_one": re.compile(r"ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE", re.I),
    "source_route": re.compile(r"ROUTE_ERROR_SOURCE_ROUTE_FAILURE", re.I),
    "non_tree_link": re.compile(r"ROUTE_ERROR_NON_TREE_LINK_FAILURE", re.I),
    "other_route_error": re.compile(r"ROUTE_ERROR_(?!MANY_TO_ONE_ROUTE_FAILURE|SOURCE_ROUTE_FAILURE|NON_TREE_LINK_FAILURE)[A-Z0-9_]+", re.I),
}

SOFT_PATTERNS = {
    "failed_ping": re.compile(r"Failed to ping", re.I),
    "timeout": re.compile(r"timed out after|\bTIMEOUT\b", re.I),
}


def analyze(lines: Iterable[str]) -> dict[str, object]:
    hard = Counter()
    routing = Counter()
    soft = Counter()
    route_nwk = Counter()
    first_ts = None
    last_ts = None
    line_count = 0

    for line in lines:
        line_count += 1
        ts = TIMESTAMP_RE.search(line)
        if ts:
            first_ts = first_ts or ts.group(1)
            last_ts = ts.group(1)
        for name, pattern in HARD_PATTERNS.items():
            if pattern.search(line):
                hard[name] += 1
        route_hit = False
        for name, pattern in ROUTE_PATTERNS.items():
            if pattern.search(line):
                routing[name] += 1
                route_hit = True
        if route_hit:
            # Ember route-error log form ends with: for "<network address>".
            matches = re.findall(r'for\s+["\']?(\d{1,5})["\']?', line)
            for nwk in matches:
                route_nwk[nwk] += 1
        for name, pattern in SOFT_PATTERNS.items():
            if pattern.search(line):
                soft[name] += 1

    hard_total = sum(hard.values())
    route_total = sum(routing.values())
    return {
        "line_count": line_count,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "hard": {name: hard[name] for name in HARD_PATTERNS},
        "hard_total": hard_total,
        "routing": {name: routing[name] for name in ROUTE_PATTERNS},
        "route_total": route_total,
        "route_nwk": dict(route_nwk.most_common()),
        "soft": {name: soft[name] for name in SOFT_PATTERNS},
        "verdict": "HARD_REGRESSION" if hard_total else ("ROUTING_CHURN" if route_total else "CLEAN"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="*", type=Path, help="Zigbee2MQTT logs; stdin if omitted")
    ap.add_argument("--fail-hard", action="store_true", help="exit 2 when a hard regression is present")
    args = ap.parse_args()

    if args.files:
        lines: list[str] = []
        for path in args.files:
            lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
    else:
        lines = list(sys.stdin)

    report = analyze(lines)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.fail_hard and report["hard_total"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
