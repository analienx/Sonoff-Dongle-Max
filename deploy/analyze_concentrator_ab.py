#!/usr/bin/env python3
"""Compare two quiet Zigbee2MQTT Ember concentrator log windows.

The analyzer is deliberately read-only. It verifies that the intended
stack_config.json profile was actually loaded, rejects samples contaminated by
full-network management scans, and compares ordinary route/hard/soft failure
rates without treating route-repair logs as proof of an NCP resource defect.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from analyze_route_health import analyze

STACK_CONFIG_RE = re.compile(r"Using stack config\s+(\{.*\})\.?", re.I)
DEFAULT_STACK_RE = re.compile(r"Using default stack config", re.I)
CONCENTRATOR_RE = re.compile(
    r"\[CONCENTRATOR\]\s+Started source route discovery\.\s+(\d+)ms until next broadcast",
    re.I,
)
TIMESTAMP_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
MANAGEMENT_SCAN_RE = re.compile(
    r"Mgmt_(?:Rtg|Lqi)|mgmtRtg|mgmtLqi|networkmap|network map request|route table request",
    re.I,
)

PROFILE_KEYS = (
    "CONCENTRATOR_RAM_TYPE",
    "CONCENTRATOR_MIN_TIME",
    "CONCENTRATOR_MAX_TIME",
    "CONCENTRATOR_ROUTE_ERROR_THRESHOLD",
    "CONCENTRATOR_DELIVERY_FAILURE_THRESHOLD",
    "CONCENTRATOR_MAX_HOPS",
)


def _duration_hours(lines: list[str]) -> float:
    stamps = []
    for line in lines:
        match = TIMESTAMP_RE.search(line)
        if match:
            stamps.append(datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
    if len(stamps) < 2:
        return 0.0
    seconds = (stamps[-1] - stamps[0]).total_seconds()
    return max(seconds / 3600.0, 0.0)


def _rate(count: int, hours: float) -> float | None:
    return None if hours <= 0 else count / hours


def summarize(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    health = analyze(lines)
    stack_config = None
    default_stack = False
    next_mtorr_ms = None
    scan_markers = 0

    for line in lines:
        cfg = STACK_CONFIG_RE.search(line)
        if cfg:
            try:
                stack_config = json.loads(cfg.group(1))
            except json.JSONDecodeError:
                pass
        if DEFAULT_STACK_RE.search(line):
            default_stack = True
        conc = CONCENTRATOR_RE.search(line)
        if conc:
            next_mtorr_ms = int(conc.group(1))
        if MANAGEMENT_SCAN_RE.search(line):
            scan_markers += 1

    hours = _duration_hours(lines)
    soft_total = sum(health["soft"].values())
    result = {
        "path": str(path),
        "duration_hours": round(hours, 6),
        "stack_config": stack_config,
        "used_default_stack_config": default_stack,
        "next_mtorr_ms": next_mtorr_ms,
        "management_scan_markers": scan_markers,
        "health": health,
        "route_rate_per_hour": _rate(health["route_total"], hours),
        "hard_rate_per_hour": _rate(health["hard_total"], hours),
        "soft_total": soft_total,
        "soft_rate_per_hour": _rate(soft_total, hours),
    }
    return result


def _profile_matches(summary: dict[str, object], minimum: int, maximum: int) -> bool:
    config = summary.get("stack_config")
    if not isinstance(config, dict):
        return False
    return (
        config.get("CONCENTRATOR_MIN_TIME") == minimum
        and config.get("CONCENTRATOR_MAX_TIME") == maximum
    )


def compare(
    baseline: dict[str, object],
    candidate: dict[str, object],
    baseline_profile: tuple[int, int],
    candidate_profile: tuple[int, int],
) -> dict[str, object]:
    reasons: list[str] = []

    if baseline["management_scan_markers"] or candidate["management_scan_markers"]:
        verdict = "INVALID_SAMPLE"
        reasons.append("management-scan traffic detected; use ordinary/quiet traffic only")
    elif not _profile_matches(baseline, *baseline_profile):
        verdict = "PROFILE_NOT_CONFIRMED"
        reasons.append(f"baseline did not confirm {baseline_profile[0]}/{baseline_profile[1]}")
    elif not _profile_matches(candidate, *candidate_profile):
        verdict = "PROFILE_NOT_CONFIRMED"
        reasons.append(f"candidate did not confirm {candidate_profile[0]}/{candidate_profile[1]}")
    elif candidate["health"]["hard_total"] > baseline["health"]["hard_total"]:
        verdict = "HARD_REGRESSION"
        reasons.append("candidate introduced additional hard coordinator/NCP failures")
    else:
        br = baseline["route_rate_per_hour"]
        cr = candidate["route_rate_per_hour"]
        bs = baseline["soft_rate_per_hour"]
        cs = candidate["soft_rate_per_hour"]
        if br is None or cr is None or bs is None or cs is None:
            verdict = "INCONCLUSIVE"
            reasons.append("timestamps do not span a measurable window")
        else:
            route_delta = cr - br
            soft_delta = cs - bs
            if cr < br and cs <= bs:
                verdict = "IMPROVED"
                reasons.append("route and soft failure rates both improved or held")
            elif br == 0 and cr > 0:
                verdict = "WORSE_ROUTING"
                reasons.append("candidate introduced routing churn into a clean baseline")
            elif br > 0 and cr > br * 1.20:
                verdict = "WORSE_ROUTING"
                reasons.append("candidate route-error rate increased by more than 20%")
            elif cs > bs * 1.20 and cs - bs > 1.0:
                verdict = "WORSE_SOFT_FAILURES"
                reasons.append("candidate soft-failure rate increased materially")
            else:
                verdict = "NO_CLEAR_CHANGE"
                reasons.append("no hard regression, but improvement is not decisive")
            reasons.append(f"route_rate_delta_per_hour={route_delta:.3f}")
            reasons.append(f"soft_rate_delta_per_hour={soft_delta:.3f}")

    return {
        "baseline_profile": {"min": baseline_profile[0], "max": baseline_profile[1]},
        "candidate_profile": {"min": candidate_profile[0], "max": candidate_profile[1]},
        "baseline": baseline,
        "candidate": candidate,
        "verdict": verdict,
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--baseline-min", type=int, default=5)
    parser.add_argument("--baseline-max", type=int, default=60)
    parser.add_argument("--candidate-min", type=int, default=10)
    parser.add_argument("--candidate-max", type=int, default=120)
    parser.add_argument("--fail-regression", action="store_true")
    args = parser.parse_args()

    report = compare(
        summarize(args.baseline),
        summarize(args.candidate),
        (args.baseline_min, args.baseline_max),
        (args.candidate_min, args.candidate_max),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.fail_regression and report["verdict"] in {
        "INVALID_SAMPLE",
        "PROFILE_NOT_CONFIRMED",
        "HARD_REGRESSION",
        "WORSE_ROUTING",
        "WORSE_SOFT_FAILURES",
    }:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
