#!/usr/bin/env python3
"""Compare ordinary-traffic concentrator route-error-threshold A/B windows.

This is read-only. It verifies the exact runtime concentrator profile, rejects
management-scan contaminated samples, preserves P013 hard-regression gates,
and measures both normalized route-error rate and same-destination bursts.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from analyze_route_health import analyze

TS_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
STACK_RE = re.compile(r"Using stack config\s+(\{.*\})\.?", re.I)
ROUTE_RE = re.compile(
    r"ROUTE_ERROR_(MANY_TO_ONE_ROUTE_FAILURE|SOURCE_ROUTE_FAILURE|NON_TREE_LINK_FAILURE).*?for\s+[\"']?(\d{1,5})",
    re.I,
)
SCAN_RE = re.compile(r"Mgmt_(?:Rtg|Lqi)|mgmtRtg|mgmtLqi|networkmap|network map request|route table request", re.I)

def _hours(lines: list[str]) -> float:
    stamps = [
        datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        for line in lines
        if (m := TS_RE.search(line))
    ]
    if len(stamps) < 2:
        return 0.0
    return max((stamps[-1] - stamps[0]).total_seconds() / 3600.0, 0.0)


def _rate(count: int, hours: float) -> float | None:
    return None if hours <= 0 else count / hours


def _burst_stats(lines: list[str], burst_seconds: int = 10) -> dict[str, object]:
    per_nwk: dict[str, list[datetime]] = defaultdict(list)
    for line in lines:
        rm = ROUTE_RE.search(line)
        tm = TS_RE.search(line)
        if rm and tm:
            per_nwk[rm.group(2)].append(datetime.strptime(tm.group(1), "%Y-%m-%d %H:%M:%S"))

    groups: list[tuple[str, int]] = []
    for nwk, stamps in per_nwk.items():
        size = 1
        for prev, cur in zip(stamps, stamps[1:]):
            if (cur - prev).total_seconds() <= burst_seconds:
                size += 1
            else:
                if size > 1:
                    groups.append((nwk, size))
                size = 1
        if size > 1:
            groups.append((nwk, size))

    excess = sum(size - 1 for _, size in groups)
    return {
        "burst_seconds": burst_seconds,
        "burst_groups": len(groups),
        "burst_event_excess": excess,
        "max_burst_size": max((size for _, size in groups), default=1),
        "bursts_by_nwk": {
            nwk: max(size for key, size in groups if key == nwk)
            for nwk in sorted({key for key, _ in groups})
        },
    }


def summarize(path: Path, burst_seconds: int = 10) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    stack_config = None
    scan_markers = 0
    for line in lines:
        if sm := STACK_RE.search(line):
            try:
                stack_config = json.loads(sm.group(1))
            except json.JSONDecodeError:
                pass
        if SCAN_RE.search(line):
            scan_markers += 1

    health = analyze(lines)
    hours = _hours(lines)
    burst = _burst_stats(lines, burst_seconds)
    soft_total = sum(health["soft"].values())
    return {
        "path": str(path),
        "duration_hours": round(hours, 6),
        "stack_config": stack_config,
        "management_scan_markers": scan_markers,
        "health": health,
        "route_rate_per_hour": _rate(health["route_total"], hours),
        "soft_total": soft_total,
        "soft_rate_per_hour": _rate(soft_total, hours),
        "burst": burst,
        "burst_excess_rate_per_hour": _rate(int(burst["burst_event_excess"]), hours),
    }


def load_inventory(path: Path | None) -> dict[str, dict[str, object]]:
    if path is None:
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, list):
        raise ValueError("inventory must be a Zigbee2MQTT bridge/devices JSON array")
    out: dict[str, dict[str, object]] = {}
    for device in doc:
        if not isinstance(device, dict):
            continue
        nwk = device.get("network_address")
        if isinstance(nwk, int):
            out[str(nwk)] = {
                "friendly_name": device.get("friendly_name"),
                "ieee_address": device.get("ieee_address"),
                "type": device.get("type"),
                "model_id": device.get("model_id"),
                "manufacturer": device.get("manufacturer"),
            }
    return out


def decorate_targets(summary: dict[str, object], inventory: dict[str, dict[str, object]]) -> None:
    route_nwk = summary["health"].get("route_nwk", {})
    resolved = {}
    unresolved = {}
    for nwk, count in route_nwk.items():
        if nwk in inventory:
            resolved[nwk] = {"count": count, **inventory[nwk]}
        else:
            unresolved[nwk] = count
    summary["route_targets"] = {"resolved": resolved, "unresolved": unresolved}


def _profile_matches(summary: dict[str, object], minimum: int, maximum: int, threshold: int) -> bool:
    cfg = summary.get("stack_config")
    return isinstance(cfg, dict) and (
        cfg.get("CONCENTRATOR_RAM_TYPE") == "high"
        and cfg.get("CONCENTRATOR_MIN_TIME") == minimum
        and cfg.get("CONCENTRATOR_MAX_TIME") == maximum
        and cfg.get("CONCENTRATOR_ROUTE_ERROR_THRESHOLD") == threshold
        and cfg.get("CONCENTRATOR_DELIVERY_FAILURE_THRESHOLD") == 1
    )


def compare(
    baseline: dict[str, object],
    candidate: dict[str, object],
    *,
    baseline_profile: tuple[int, int, int],
    candidate_profile: tuple[int, int, int],
) -> dict[str, object]:
    reasons: list[str] = []
    if baseline["management_scan_markers"] or candidate["management_scan_markers"]:
        verdict = "INVALID_SAMPLE"
        reasons.append("management-scan traffic detected")
    elif not _profile_matches(baseline, *baseline_profile):
        verdict = "PROFILE_NOT_CONFIRMED"
        reasons.append(f"baseline profile not confirmed: {baseline_profile}")
    elif not _profile_matches(candidate, *candidate_profile):
        verdict = "PROFILE_NOT_CONFIRMED"
        reasons.append(f"candidate profile not confirmed: {candidate_profile}")
    elif candidate["health"]["hard_total"] > baseline["health"]["hard_total"]:
        verdict = "HARD_REGRESSION"
        reasons.append("candidate introduced additional hard coordinator/NCP failures")
    else:
        br = baseline["route_rate_per_hour"]
        cr = candidate["route_rate_per_hour"]
        bs = baseline["soft_rate_per_hour"]
        cs = candidate["soft_rate_per_hour"]
        bb = baseline["burst_excess_rate_per_hour"]
        cb = candidate["burst_excess_rate_per_hour"]
        if None in {br, cr, bs, cs, bb, cb}:
            verdict = "INCONCLUSIVE"
            reasons.append("timestamps do not span a measurable window")
        elif cr < br and cb < bb and cs <= bs * 1.20:
            verdict = "IMPROVED"
            reasons.append("route rate and same-destination burst rate both improved without material soft-failure regression")
        elif br > 0 and cr > br * 1.20:
            verdict = "WORSE_ROUTING"
            reasons.append("route-error rate increased by more than 20%")
        elif bb > 0 and cb > bb * 1.20 and cb - bb > 1.0:
            verdict = "WORSE_BURSTS"
            reasons.append("same-destination route-error burst rate increased materially")
        elif cs > bs * 1.20 and cs - bs > 1.0:
            verdict = "WORSE_SOFT_FAILURES"
            reasons.append("soft-failure rate increased materially")
        else:
            verdict = "NO_CLEAR_CHANGE"
            reasons.append("no hard regression, but improvement is not decisive")
        reasons.extend(
            [
                f"route_rate_delta_per_hour={cr - br:.3f}",
                f"burst_excess_rate_delta_per_hour={cb - bb:.3f}",
                f"soft_rate_delta_per_hour={cs - bs:.3f}",
            ]
        )

    return {
        "baseline_profile": {"min": baseline_profile[0], "max": baseline_profile[1], "route_error_threshold": baseline_profile[2]},
        "candidate_profile": {"min": candidate_profile[0], "max": candidate_profile[1], "route_error_threshold": candidate_profile[2]},
        "baseline": baseline,
        "candidate": candidate,
        "verdict": verdict,
        "reasons": reasons,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--baseline-threshold", type=int, default=3)
    ap.add_argument("--candidate-threshold", type=int, default=1)
    ap.add_argument("--min-time", type=int, default=5)
    ap.add_argument("--max-time", type=int, default=60)
    ap.add_argument("--burst-seconds", type=int, default=10)
    ap.add_argument("--fail-regression", action="store_true")
    ap.add_argument("--inventory", type=Path, help="optional Zigbee2MQTT bridge/devices JSON array for route-target attribution")
    args = ap.parse_args()
    baseline = summarize(args.baseline, args.burst_seconds)
    candidate = summarize(args.candidate, args.burst_seconds)
    inventory = load_inventory(args.inventory)
    if inventory:
        decorate_targets(baseline, inventory)
        decorate_targets(candidate, inventory)
    report = compare(
        baseline,
        candidate,
        baseline_profile=(args.min_time, args.max_time, args.baseline_threshold),
        candidate_profile=(args.min_time, args.max_time, args.candidate_threshold),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.fail_regression and report["verdict"] in {
        "INVALID_SAMPLE",
        "PROFILE_NOT_CONFIRMED",
        "HARD_REGRESSION",
        "WORSE_ROUTING",
        "WORSE_BURSTS",
        "WORSE_SOFT_FAILURES",
    }:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
