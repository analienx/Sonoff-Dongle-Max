#!/usr/bin/env python3
"""Decode zigbee-herdsman `[NCP COUNTERS]` vectors into useful pressure signals.

Herdsman 10.9.1 reads *and clears* Ember counters hourly, so each logged vector is
already an interval count. This tool is read-only and safe to run against retained
logs; it never connects to the coordinator.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

MARKER = "[NCP COUNTERS]"
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T|[ .])\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")

# Pinned zigbee-herdsman 10.9.1 EmberCounterType indices.
TRAFFIC = {
    0: "MAC_RX_BROADCAST",
    1: "MAC_TX_BROADCAST",
    2: "MAC_RX_UNICAST",
    3: "MAC_TX_UNICAST_SUCCESS",
    4: "MAC_TX_UNICAST_RETRY",
    5: "MAC_TX_UNICAST_FAILED",
}

SELECTED = {
    18: "ASH_OVERFLOW_ERROR",
    19: "ASH_FRAMING_ERROR",
    20: "ASH_OVERRUN_ERROR",
    27: "ALLOCATE_PACKET_BUFFER_FAILURE",
    29: "PHY_TO_MAC_QUEUE_LIMIT_REACHED",
    31: "NWK_RETRY_OVERFLOW",
    32: "PHY_CCA_FAIL_COUNT",
    33: "BROADCAST_TABLE_FULL",
    40: "ADDRESS_CONFLICT_SENT",
}
EXPECTED_COUNTER_COUNT = 42


def decode_line(line: str, *, source: str, line_number: int) -> dict[str, object] | None:
    if MARKER not in line:
        return None
    payload = line.split(MARKER, 1)[1].strip()
    values: list[int] = []
    for token in payload.split(","):
        token = token.strip()
        if not token:
            continue
        if not re.fullmatch(r"\d+", token):
            raise ValueError(f"{source}:{line_number}: malformed NCP counter token {token!r}")
        values.append(int(token))
    if len(values) < max(SELECTED) + 1:
        raise ValueError(f"{source}:{line_number}: counter vector too short: {len(values)}")

    ts = TIMESTAMP_RE.search(line.split(MARKER, 1)[0])
    selected = {name: values[index] for index, name in SELECTED.items()}
    traffic = {name: values[index] for index, name in TRAFFIC.items()}
    tx_events = (
        traffic["MAC_TX_BROADCAST"]
        + traffic["MAC_TX_UNICAST_SUCCESS"]
        + traffic["MAC_TX_UNICAST_RETRY"]
        + traffic["MAC_TX_UNICAST_FAILED"]
        + selected["PHY_CCA_FAIL_COUNT"]
    )
    cca_per_1000 = None if tx_events == 0 else round(selected["PHY_CCA_FAIL_COUNT"] * 1000.0 / tx_events, 3)
    return {
        "source": source,
        "line": line_number,
        "timestamp": ts.group(0) if ts else None,
        "counter_count": len(values),
        "expected_counter_count": EXPECTED_COUNTER_COUNT,
        "selected": selected,
        "traffic": traffic,
        "cca_fail_per_1000_tx_events": cca_per_1000,
        "nonzero_pressure": {k: v for k, v in selected.items() if v != 0},
    }


def decode_lines(lines: Iterable[str], *, source: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, 1):
        rec = decode_line(line, source=source, line_number=line_number)
        if rec is not None:
            out.append(rec)
    return out


def summary(records: list[dict[str, object]]) -> dict[str, object]:
    totals = {name: 0 for name in SELECTED.values()}
    maxima = {name: 0 for name in SELECTED.values()}
    nonzero_intervals = {name: 0 for name in SELECTED.values()}
    traffic_totals = {name: 0 for name in TRAFFIC.values()}
    traffic_maxima = {name: 0 for name in TRAFFIC.values()}
    for rec in records:
        selected = rec["selected"]
        assert isinstance(selected, dict)
        for name in totals:
            value = int(selected[name])
            totals[name] += value
            maxima[name] = max(maxima[name], value)
            if value:
                nonzero_intervals[name] += 1
        traffic = rec.get("traffic")
        if isinstance(traffic, dict):
            for name in traffic_totals:
                value = int(traffic[name])
                traffic_totals[name] += value
                traffic_maxima[name] = max(traffic_maxima[name], value)
    tx_events = (
        traffic_totals["MAC_TX_BROADCAST"]
        + traffic_totals["MAC_TX_UNICAST_SUCCESS"]
        + traffic_totals["MAC_TX_UNICAST_RETRY"]
        + traffic_totals["MAC_TX_UNICAST_FAILED"]
        + totals["PHY_CCA_FAIL_COUNT"]
    )
    return {
        "intervals": len(records),
        "totals": totals,
        "max_per_interval": maxima,
        "nonzero_intervals": nonzero_intervals,
        "traffic_totals": traffic_totals,
        "traffic_max_per_interval": traffic_maxima,
        "cca_fail_per_1000_tx_events": None if tx_events == 0 else round(totals["PHY_CCA_FAIL_COUNT"] * 1000.0 / tx_events, 3),
    }


def read_path(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return decode_lines(fh, source=str(path))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="*", type=Path, help="retained Zigbee2MQTT log files; stdin if omitted")
    ap.add_argument("--json", action="store_true", help="emit one JSON object containing records and summary")
    args = ap.parse_args()

    records: list[dict[str, object]] = []
    if args.files:
        for path in args.files:
            records.extend(read_path(path))
    else:
        records = decode_lines(sys.stdin, source="stdin")

    report = {"records": records, "summary": summary(records)}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    if not records:
        print("No [NCP COUNTERS] lines found.")
        return
    for rec in records:
        selected = rec["selected"]
        assert isinstance(selected, dict)
        timestamp = rec.get("timestamp") or "?"
        signals = " ".join(f"{name}={selected[name]}" for name in SELECTED.values())
        print(f"{timestamp} {rec['source']}:{rec['line']} {signals}")
    print("\nSUMMARY")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
