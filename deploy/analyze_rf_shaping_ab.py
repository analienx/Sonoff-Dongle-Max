#!/usr/bin/env python3
"""Compare ordinary-traffic before/after windows for bidirectional RF topology shaping.

This is read-only. It reuses the P014 ordinary-traffic summarizer, rejects
management-scan contaminated samples, verifies the production concentrator
profile did not drift, and judges whether a passive RF attenuation change
reduced routing churn without introducing hard or user-visible regressions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_route_threshold_ab import (
    _profile_matches,
    decorate_targets,
    load_inventory,
    summarize,
)


def _pct_change(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    if before == 0:
        return 0.0 if after == 0 else None
    return ((after - before) / before) * 100.0


def compare(
    baseline: dict[str, object],
    candidate: dict[str, object],
    *,
    baseline_attenuation_db: float,
    candidate_attenuation_db: float,
    profile: tuple[int, int, int] = (5, 60, 3),
    improvement_gate_pct: float = 30.0,
) -> dict[str, object]:
    reasons: list[str] = []
    verdict = "NO_CLEAR_CHANGE"

    if candidate_attenuation_db <= baseline_attenuation_db:
        verdict = "INVALID_EXPERIMENT"
        reasons.append("candidate attenuation must be greater than baseline attenuation")
    elif baseline["management_scan_markers"] or candidate["management_scan_markers"]:
        verdict = "INVALID_SAMPLE"
        reasons.append("management-scan traffic detected")
    elif not _profile_matches(baseline, *profile):
        verdict = "PROFILE_NOT_CONFIRMED"
        reasons.append(f"baseline concentrator profile not confirmed: {profile}")
    elif not _profile_matches(candidate, *profile):
        verdict = "PROFILE_NOT_CONFIRMED"
        reasons.append(f"candidate concentrator profile not confirmed: {profile}")
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
        else:
            route_pct = _pct_change(br, cr)
            burst_pct = _pct_change(bb, cb)
            soft_pct = _pct_change(bs, cs)
            required_ratio = 1.0 - improvement_gate_pct / 100.0

            if (
                br > 0
                and cr <= br * required_ratio
                and cb <= max(bb * 1.20, bb + 1.0)
                and cs <= max(bs * 1.20, bs + 1.0)
            ):
                verdict = "IMPROVED"
                reasons.append(
                    f"route-error rate improved by at least {improvement_gate_pct:.1f}% "
                    "without material burst or soft-failure regression"
                )
            elif br > 0 and cr > br * 1.20:
                verdict = "WORSE_ROUTING"
                reasons.append("route-error rate increased by more than 20%")
            elif bb > 0 and cb > bb * 1.20 and cb - bb > 1.0:
                verdict = "WORSE_BURSTS"
                reasons.append("same-destination route-error burst rate increased materially")
            elif cs > max(bs * 1.20, bs + 1.0):
                verdict = "WORSE_SOFT_FAILURES"
                reasons.append("soft-failure rate increased materially")
            else:
                reasons.append("no hard regression, but the RF-shaping benefit is not decisive")

            reasons.extend(
                [
                    f"route_rate_delta_per_hour={cr - br:.3f}",
                    f"route_rate_change_pct={route_pct if route_pct is not None else 'n/a'}",
                    f"burst_excess_rate_delta_per_hour={cb - bb:.3f}",
                    f"burst_excess_change_pct={burst_pct if burst_pct is not None else 'n/a'}",
                    f"soft_rate_delta_per_hour={cs - bs:.3f}",
                    f"soft_rate_change_pct={soft_pct if soft_pct is not None else 'n/a'}",
                ]
            )

    return {
        "experiment": {
            "baseline_attenuation_db": baseline_attenuation_db,
            "candidate_attenuation_db": candidate_attenuation_db,
            "attenuation_delta_db": candidate_attenuation_db - baseline_attenuation_db,
            "concentrator_profile": {
                "min": profile[0],
                "max": profile[1],
                "route_error_threshold": profile[2],
                "delivery_failure_threshold": 1,
            },
            "improvement_gate_pct": improvement_gate_pct,
        },
        "baseline": baseline,
        "candidate": candidate,
        "verdict": verdict,
        "reasons": reasons,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--baseline-attenuation-db", type=float, default=0.0)
    ap.add_argument("--candidate-attenuation-db", type=float, default=3.0)
    ap.add_argument("--min-time", type=int, default=5)
    ap.add_argument("--max-time", type=int, default=60)
    ap.add_argument("--route-error-threshold", type=int, default=3)
    ap.add_argument("--burst-seconds", type=int, default=10)
    ap.add_argument("--improvement-gate-pct", type=float, default=30.0)
    ap.add_argument("--inventory", type=Path)
    ap.add_argument("--fail-regression", action="store_true")
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
        baseline_attenuation_db=args.baseline_attenuation_db,
        candidate_attenuation_db=args.candidate_attenuation_db,
        profile=(args.min_time, args.max_time, args.route_error_threshold),
        improvement_gate_pct=args.improvement_gate_pct,
    )
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.fail_regression and report["verdict"] in {
        "INVALID_EXPERIMENT",
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
