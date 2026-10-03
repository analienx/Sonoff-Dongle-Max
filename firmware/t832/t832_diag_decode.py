#!/usr/bin/env python3
"""Decode T832-DIAG-R0 DEBUG.msg records from existing host log files.

This collector never opens the coordinator serial device. It consumes only
already-written logs, preserving the raw source line and host/source timing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import struct
import sys
from pathlib import Path
from typing import Iterable

PREFIX = "T832D1:"
PACKET_SIZE = 52
HEX_RE = re.compile(r"T832D1:([0-9A-Fa-f]{104})(?![0-9A-Fa-f])")
ISO_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d:[0-6]\d"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
HEADER = struct.Struct("<4sBBHHQIIHHH")
RECORD = struct.Struct("<IIHBBHHHH")

EVENT_NAMES = {
    1: "BOOT",
    2: "MT_COMMAND_RX",
    3: "MT_COMMAND_DISPATCH",
    4: "MT_COMMAND_COMPLETE",
    5: "RESPONSE_QUEUED",
    6: "RESPONSE_ALLOC_FAIL",
    7: "NPI_RX_PROGRESS",
    8: "NPI_RX_OVERFLOW",
    9: "NPI_WRITE_REJECT",
    10: "NPI_TX_FINISHED",
    11: "TASK_SCHEDULE",
    12: "TASK_WORK",
    13: "STARTUP_FROM_APP_ENTRY",
    14: "STARTUP_BDB_REQUEST",
    15: "STARTUP_BDB_RETURN",
    16: "STARTUP_SRSP_QUEUE",
    17: "BDB_DISPATCH",
    18: "BDB_RETURN",
    19: "HEALTH",
    20: "RESOURCE",
    21: "EXPORT_SKIP",
    22: "FIRST_FAULT",
    23: "RX_BUFFER_FULL",
    24: "NETWORK_STATE",
    25: "TRANSPORT_CONFIG",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def source_utc(line: str) -> str | None:
    match = ISO_RE.search(line)
    if not match:
        return None
    raw = match.group("ts").replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    elif re.search(r"[+-]\d{4}$", raw):
        raw = raw[:-5] + raw[-5:-2] + ":" + raw[-2:]
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def fingerprint_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class Continuity:
    def __init__(self, collector_id: str) -> None:
        self.collector_id = collector_id
        self.host_session = 0
        self.last_export_sequence: int | None = None
        self.last_uptime_ms: int | None = None

    def annotate(self, export_sequence: int, uptime_ms: int) -> dict[str, object]:
        reset = False
        if self.last_export_sequence is None:
            self.host_session += 1
        elif (
            export_sequence <= self.last_export_sequence
            or (self.last_uptime_ms is not None and uptime_ms < self.last_uptime_ms)
        ):
            self.host_session += 1
            reset = True

        gap = 0
        if not reset and self.last_export_sequence is not None:
            gap = max(0, export_sequence - self.last_export_sequence - 1)

        self.last_export_sequence = export_sequence
        self.last_uptime_ms = uptime_ms
        return {
            "collector_id": self.collector_id,
            "host_session": self.host_session,
            "sequence_gap_before": gap,
            "session_reset_detected": reset,
        }


def decode_payload(hex_payload: str) -> dict[str, object]:
    raw = bytes.fromhex(hex_payload)
    if len(raw) != PACKET_SIZE:
        raise ValueError(f"unexpected packet length {len(raw)}")
    (
        magic,
        schema,
        packet_kind,
        export_sequence,
        boot_session,
        uptime_ms,
        firmware_revision,
        capabilities,
        critical_overwrite,
        routine_overwrite,
        export_skipped,
    ) = HEADER.unpack_from(raw, 0)
    if magic != b"T8D1":
        raise ValueError("bad T832 diagnostic magic")
    if schema != 1:
        raise ValueError(f"unsupported schema {schema}")
    (
        first_ms,
        last_ms,
        record_sequence,
        event_kind,
        flags,
        a,
        b,
        c,
        repeat_count,
    ) = RECORD.unpack_from(raw, HEADER.size)
    return {
        "signature": magic.decode("ascii"),
        "schema": schema,
        "packet_kind": packet_kind,
        "export_sequence": export_sequence,
        "firmware_boot_session": boot_session,
        "firmware_uptime_ms": uptime_ms,
        "firmware_revision": firmware_revision,
        "capability_bitmap": f"0x{capabilities:08x}",
        "critical_overwrite": critical_overwrite,
        "routine_overwrite": routine_overwrite,
        "export_skipped": export_skipped,
        "record": {
            "first_ms": first_ms,
            "last_ms": last_ms,
            "sequence": record_sequence,
            "kind": event_kind,
            "kind_name": EVENT_NAMES.get(event_kind, "UNKNOWN"),
            "critical": bool(flags & 1),
            "flags": flags,
            "a": a,
            "b": b,
            "c": c,
            "repeat_count": repeat_count,
        },
    }


def iter_records(
    paths: Iterable[Path],
    *,
    collector_id: str,
    firmware_sha256: str | None,
    config_fingerprint: str | None,
) -> Iterable[dict[str, object]]:
    continuity = Continuity(collector_id)
    collector_sequence = 0
    for path in paths:
        try:
            fh = path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            yield {
                "type": "source_error",
                "collector_utc": utc_now(),
                "source_file": str(path),
                "error": str(exc),
            }
            continue
        with fh:
            for line_number, line in enumerate(fh, 1):
                for match in HEX_RE.finditer(line):
                    collector_sequence += 1
                    payload_hex = match.group(1)
                    try:
                        decoded = decode_payload(payload_hex)
                    except ValueError as exc:
                        yield {
                            "type": "decode_error",
                            "collector_utc": utc_now(),
                            "collector_sequence": collector_sequence,
                            "source_file": str(path),
                            "source_line": line_number,
                            "source_utc": source_utc(line),
                            "raw_line": line.rstrip("\r\n"),
                            "raw_payload_hex": payload_hex,
                            "error": str(exc),
                        }
                        continue
                    decoded.update(
                        continuity.annotate(
                            int(decoded["export_sequence"]),
                            int(decoded["firmware_uptime_ms"]),
                        )
                    )
                    decoded.update(
                        {
                            "type": "t832_diag",
                            "collector_utc": utc_now(),
                            "collector_sequence": collector_sequence,
                            "source_file": str(path),
                            "source_line": line_number,
                            "source_utc": source_utc(line),
                            "raw_line": line.rstrip("\r\n"),
                            "raw_payload_hex": payload_hex,
                            "firmware_sha256": firmware_sha256,
                            "config_fingerprint": config_fingerprint,
                        }
                    )
                    yield decoded


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--collector-id", default="t832-host-collector")
    ap.add_argument("--firmware-sha256")
    ap.add_argument("--firmware-image", type=Path)
    ap.add_argument("--config-fingerprint")
    args = ap.parse_args()

    firmware_sha = args.firmware_sha256
    if args.firmware_image:
        image_sha = fingerprint_file(args.firmware_image)
        if firmware_sha and firmware_sha.lower() != image_sha:
            raise SystemExit("provided firmware SHA256 does not match firmware image")
        firmware_sha = image_sha

    output = args.output.open("w", encoding="utf-8") if args.output else sys.stdout
    try:
        for item in iter_records(
            args.logs,
            collector_id=args.collector_id,
            firmware_sha256=firmware_sha,
            config_fingerprint=args.config_fingerprint,
        ):
            output.write(json.dumps(item, separators=(",", ":"), sort_keys=True) + "\n")
    finally:
        if output is not sys.stdout:
            output.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
