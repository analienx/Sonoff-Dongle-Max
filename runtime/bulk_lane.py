#!/usr/bin/env python3
"""Bounded coordinator-originated bulk-operation pacing.

This module is intentionally host-side. It never retries BUSY responses and it never
changes normal single-device/direct-bound traffic. Callers opt into this lane only
for explicit broad/group operations.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

SAFE_FINAL_STATE_KEYS = frozenset({"state", "brightness", "color_temp", "color", "effect"})
UNSAFE_ACTION_KEYS = frozenset({"toggle", "brightness_step", "brightness_move", "color_temp_step", "color_temp_move", "hue_step", "saturation_step", "transition_step"})


@dataclass(frozen=True)
class BulkCommand:
    target: str
    payload: dict
    safety_critical: bool = False
    label: str = ""


@dataclass(frozen=True)
class ScheduledCommand:
    index: int
    target: str
    payload: dict
    not_before_ms: int
    safety_critical: bool
    label: str


def _upper_state(payload: dict) -> str | None:
    value = payload.get("state")
    return value.upper() if isinstance(value, str) else None


def is_coalescible(command: BulkCommand) -> bool:
    """Only deterministic final-state assignments may be coalesced."""
    if command.safety_critical or not command.payload:
        return False
    if any(k in command.payload for k in UNSAFE_ACTION_KEYS):
        return False
    if not set(command.payload).issubset(SAFE_FINAL_STATE_KEYS):
        return False
    # OFF is deliberately retained: all-off correctness is more important than
    # reducing one queued command.
    if _upper_state(command.payload) == "OFF":
        return False
    return True


def coalesce_idempotent(commands: Sequence[BulkCommand]) -> list[BulkCommand]:
    """Keep only the last safely-coalescible command per target.

    Non-coalescible commands preserve their exact order and form barriers: commands
    are never moved across a toggle/step/safety-critical operation.
    """
    result: list[BulkCommand] = []
    segment: list[BulkCommand] = []

    def flush() -> None:
        if not segment:
            return
        last: dict[str, int] = {}
        for idx, cmd in enumerate(segment):
            if is_coalescible(cmd):
                last[cmd.target] = idx
        for idx, cmd in enumerate(segment):
            if not is_coalescible(cmd) or last.get(cmd.target) == idx:
                result.append(cmd)
        segment.clear()

    for command in commands:
        if is_coalescible(command):
            segment.append(command)
        else:
            flush()
            result.append(command)
    flush()
    return result


def schedule_bulk(
    commands: Sequence[BulkCommand],
    *,
    interval_ms: int = 1250,
    max_depth: int = 32,
    max_span_ms: int = 30000,
    coalesce: bool = True,
) -> list[ScheduledCommand]:
    if not 1000 <= interval_ms <= 2000:
        raise ValueError("interval_ms must stay within the reviewed 1000..2000 ms lane")
    if max_depth < 1:
        raise ValueError("max_depth must be positive")
    if max_span_ms < 0:
        raise ValueError("max_span_ms must be non-negative")

    materialized = list(commands)
    if len(materialized) > max_depth:
        raise ValueError(f"bulk lane depth {len(materialized)} exceeds maximum {max_depth}")
    if coalesce:
        materialized = coalesce_idempotent(materialized)
    span = max(0, (len(materialized) - 1) * interval_ms)
    if span > max_span_ms:
        raise ValueError(f"bulk lane span {span} ms exceeds maximum {max_span_ms} ms")

    return [
        ScheduledCommand(
            index=i,
            target=cmd.target,
            payload=cmd.payload,
            not_before_ms=i * interval_ms,
            safety_critical=cmd.safety_critical,
            label=cmd.label,
        )
        for i, cmd in enumerate(materialized)
    ]


def _load_commands(path: Path) -> list[BulkCommand]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("input must be a JSON list")
    result = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("target"), str) or not isinstance(item.get("payload"), dict):
            raise ValueError("each command needs string target and object payload")
        result.append(BulkCommand(
            target=item["target"], payload=item["payload"],
            safety_critical=bool(item.get("safety_critical", False)),
            label=str(item.get("label", "")),
        ))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Plan a bounded Zigbee bulk-operation lane; this tool never sends or retries commands")
    p.add_argument("input", type=Path, help="JSON list of {target,payload,...}")
    p.add_argument("--interval-ms", type=int, default=1250)
    p.add_argument("--max-depth", type=int, default=32)
    p.add_argument("--max-span-ms", type=int, default=30000)
    p.add_argument("--no-coalesce", action="store_true")
    args = p.parse_args()
    plan = schedule_bulk(_load_commands(args.input), interval_ms=args.interval_ms, max_depth=args.max_depth,
                         max_span_ms=args.max_span_ms, coalesce=not args.no_coalesce)
    print(json.dumps([asdict(x) for x in plan], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
