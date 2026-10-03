#!/usr/bin/env python3
"""T832-DIAG-R0 file-log collector, evidence barrier, and persistent incident latch.

The tool never opens the coordinator serial port. It consumes already-written
Zigbee2MQTT/Home Assistant/host logs, writes private JSONL, and gates recovery.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import struct
import sys
import time
from pathlib import Path
from typing import Iterable

PREFIX_RE = re.compile(r"T832D1:([0-9A-Fa-f]{104})(?![0-9A-Fa-f])")
ISO_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d:[0-6]\d"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
HOST_EVENT_RE = re.compile(
    r"(usb|tty|serial|cdc|disconnect|enumerat|zigbee2mqtt|addon|supervisor|"
    r"bridge|startupfromapp|srsp|timeout|rts|dtr|reset)",
    re.IGNORECASE,
)
HEADER = struct.Struct("<4sBBHHQIIHHH")
RECORD = struct.Struct("<IIHBBHHHH")
PACKET_BYTES = HEADER.size + RECORD.size

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
    26: "TASK_EVENTS",
    27: "NV_EVENT",
    28: "AF_STATE",
    29: "NV_FAULT",
}

DEFAULT_SOURCES = [
    "/addon_configs/45df7312_zigbee2mqtt/log",
    "/addon_configs/45df7312_zigbee2mqtt",
    "/config/zigbee2mqtt/log",
    "/config/home-assistant.log",
    "/config/.private/t832-diag/host-events.log",
]


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime | None = None) -> str:
    value = value or utcnow()
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(text: str) -> dt.datetime | None:
    match = ISO_RE.search(text)
    if not match:
        return None
    raw = match.group("ts").replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    elif re.search(r"[+-]\d{4}$", raw):
        raw = raw[:-5] + raw[-5:-2] + ":" + raw[-2:]
    try:
        value = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is None:
        return None
    return value.astimezone(dt.timezone.utc)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.stream = root / "stream"
        self.incidents = root / "incidents"
        self.cursor = self.state / "collector.json"
        self.latch = self.state / "incident-latch.json"
        self.firmware = root / "firmware.json"
        self.host_events = root / "host-events.log"
        for path in (self.root, self.state, self.stream, self.incidents):
            path.mkdir(parents=True, exist_ok=True)
            try:
                path.chmod(0o700)
            except OSError:
                pass

    @staticmethod
    def load(path: Path, default: object) -> object:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def fsync_dir(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    def atomic_json(self, path: Path, value: object) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        self.fsync_dir(path.parent)

    @staticmethod
    def append_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> int:
        count = 0
        with path.open("a", encoding="utf-8") as fh:
            try:
                path.chmod(0o600)
            except OSError:
                pass
            for row in rows:
                fh.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
                count += 1
            fh.flush()
            os.fsync(fh.fileno())
        return count

    def append_host_event(self, kind: str, **fields: object) -> None:
        row = {"utc": iso(), "kind": kind, **fields}
        with self.host_events.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def decode_packet(hex_payload: str) -> dict[str, object]:
    raw = bytes.fromhex(hex_payload)
    if len(raw) != PACKET_BYTES:
        raise ValueError(f"packet-size:{len(raw)}")
    hdr = HEADER.unpack_from(raw)
    if hdr[0] != b"T8D1":
        raise ValueError("bad-signature")
    if hdr[1] != 1:
        raise ValueError(f"unsupported-schema:{hdr[1]}")
    rec = RECORD.unpack_from(raw, HEADER.size)
    return {
        "signature": "T8D1",
        "schema": hdr[1],
        "packet_kind": hdr[2],
        "export_sequence": hdr[3],
        "firmware_boot_session": hdr[4],
        "firmware_uptime_ms": hdr[5],
        "firmware_revision": hdr[6],
        "capability_bitmap": f"0x{hdr[7]:08x}",
        "critical_overwrite": hdr[8],
        "routine_overwrite": hdr[9],
        "export_skipped": hdr[10],
        "record": {
            "first_ms": rec[0],
            "last_ms": rec[1],
            "sequence": rec[2],
            "kind": rec[3],
            "kind_name": EVENT_NAMES.get(rec[3], "UNKNOWN"),
            "flags": rec[4],
            "critical": bool(rec[4] & 1),
            "a": rec[5],
            "b": rec[6],
            "c": rec[7],
            "repeat_count": rec[8],
        },
    }


def source_files(values: list[str]) -> tuple[list[Path], list[str]]:
    found: dict[str, Path] = {}
    missing: list[str] = []
    for raw in values:
        path = Path(raw)
        if not path.exists():
            missing.append(str(path))
            continue
        if path.is_file():
            found[str(path)] = path
            continue
        try:
            for child in path.rglob("*"):
                if not child.is_file():
                    continue
                low = child.name.lower()
                if low.endswith((".log", ".txt", ".jsonl")):
                    found[str(child)] = child
        except OSError as exc:
            missing.append(f"{path}:{exc}")
    files = sorted(
        found.values(),
        key=lambda p: p.stat().st_mtime_ns if p.exists() else 0,
    )
    return files[-64:], sorted(set(missing))


def read_increment(path: Path, offset: int, initial_tail_bytes: int) -> tuple[list[tuple[int, str]], int]:
    size = path.stat().st_size
    if size < offset:
        offset = 0
    if offset == 0 and size > initial_tail_bytes:
        offset = size - initial_tail_bytes
    rows: list[tuple[int, str]] = []
    with path.open("rb") as fh:
        fh.seek(offset)
        if offset:
            fh.readline()
        while True:
            pos = fh.tell()
            raw = fh.readline()
            if not raw:
                break
            rows.append((pos, raw.decode("utf-8", errors="replace").rstrip("\r\n")))
        return rows, fh.tell()


def firmware_hash(store: Store) -> str | None:
    value = store.load(store.firmware, {})
    if isinstance(value, dict):
        sha = value.get("sha256")
        if isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            return sha.lower()
    return None


def collect(
    store: Store,
    sources: list[str],
    *,
    config_fingerprint: str | None,
    initial_tail_bytes: int,
    retain_days: int,
    max_bytes: int,
) -> dict[str, object]:
    state = store.load(store.cursor, {})
    if not isinstance(state, dict):
        state = {}
    cursors = state.setdefault("files", {})
    continuity = state.setdefault(
        "continuity",
        {
            "host_session": 0,
            "last_export_sequence": None,
            "last_uptime_ms": None,
            "collector_sequence": 0,
        },
    )
    files, missing = source_files(sources)
    diag_rows: list[dict[str, object]] = []
    host_rows: list[dict[str, object]] = []

    for path in files:
        key = str(path)
        prior = cursors.get(key, {}) if isinstance(cursors, dict) else {}
        offset = int(prior.get("offset", 0)) if isinstance(prior, dict) else 0
        try:
            rows, new_offset = read_increment(path, offset, initial_tail_bytes)
            stat = path.stat()
        except OSError as exc:
            missing.append(f"{path}:{exc}")
            continue
        cursors[key] = {
            "offset": new_offset,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        for byte_offset, line in rows:
            source_time = parse_timestamp(line)
            if HOST_EVENT_RE.search(line):
                host_rows.append(
                    {
                        "type": "host_event",
                        "collector_utc": iso(),
                        "source_utc": iso(source_time) if source_time else None,
                        "source_file": key,
                        "source_byte_offset": byte_offset,
                        "raw_line": line,
                    }
                )

            for match in PREFIX_RE.finditer(line):
                continuity["collector_sequence"] = int(continuity.get("collector_sequence") or 0) + 1
                collector_seq = int(continuity["collector_sequence"])
                try:
                    decoded = decode_packet(match.group(1))
                except ValueError as exc:
                    diag_rows.append(
                        {
                            "type": "decode_error",
                            "collector_utc": iso(),
                            "collector_sequence": collector_seq,
                            "source_utc": iso(source_time) if source_time else None,
                            "source_file": key,
                            "source_byte_offset": byte_offset,
                            "raw_line": line,
                            "raw_payload_hex": match.group(1),
                            "error": str(exc),
                        }
                    )
                    continue

                seq = int(decoded["export_sequence"])
                uptime = int(decoded["firmware_uptime_ms"])
                last_seq = continuity.get("last_export_sequence")
                last_uptime = continuity.get("last_uptime_ms")
                reset = (
                    last_seq is None
                    or seq <= int(last_seq)
                    or (last_uptime is not None and uptime < int(last_uptime))
                )
                if reset:
                    continuity["host_session"] = int(continuity.get("host_session") or 0) + 1
                    gap = 0
                else:
                    gap = max(0, seq - int(last_seq) - 1)
                continuity["last_export_sequence"] = seq
                continuity["last_uptime_ms"] = uptime
                decoded.update(
                    {
                        "type": "t832_diag",
                        "collector_utc": iso(),
                        "collector_sequence": collector_seq,
                        "collector_id": "t832-file-collector",
                        "host_session": continuity["host_session"],
                        "session_reset_detected": bool(reset and last_seq is not None),
                        "sequence_gap_before": gap,
                        "source_utc": iso(source_time) if source_time else None,
                        "source_file": key,
                        "source_byte_offset": byte_offset,
                        "raw_line": line,
                        "raw_payload_hex": match.group(1),
                        "firmware_sha256": firmware_hash(store),
                        "config_fingerprint": config_fingerprint,
                    }
                )
                diag_rows.append(decoded)

    day = utcnow().strftime("%Y-%m-%d")
    diag_count = store.append_jsonl(store.stream / f"diag-{day}.jsonl", diag_rows) if diag_rows else 0
    host_count = store.append_jsonl(store.stream / f"host-{day}.jsonl", host_rows) if host_rows else 0
    state["files"] = cursors
    state["continuity"] = continuity
    state["last_collect_utc"] = iso()
    state["missing_sources"] = sorted(set(missing))
    store.atomic_json(store.cursor, state)
    rotate(store, retain_days=retain_days, max_bytes=max_bytes)
    return {
        "ok": True,
        "diag_records": diag_count,
        "host_events": host_count,
        "sources_seen": len(files),
        "missing_sources": sorted(set(missing)),
        "collector_utc": iso(),
    }


def rotate(store: Store, *, retain_days: int, max_bytes: int) -> None:
    cutoff = time.time() - retain_days * 86400
    files = [p for p in store.stream.glob("*.jsonl") if p.is_file()]
    for path in files:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass
    files = sorted(
        (p for p in store.stream.glob("*.jsonl") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    total = sum(p.stat().st_size for p in files)
    for path in files:
        if total <= max_bytes:
            break
        size = path.stat().st_size
        try:
            path.unlink()
            total -= size
        except OSError:
            pass


def recent_rows(store: Store, prefix: str, cutoff: dt.datetime) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for path in sorted(store.stream.glob(f"{prefix}-*.jsonl")):
        try:
            fh = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                stamp = item.get("source_utc") or item.get("collector_utc")
                when = parse_timestamp(str(stamp)) if stamp else None
                if when is not None and when >= cutoff:
                    out.append(item)
    return out


def active_latch(value: object) -> bool:
    return isinstance(value, dict) and value.get("status") not in (None, "closed", "cleared")


def capture(
    store: Store,
    trigger: str,
    *,
    sources: list[str],
    config_fingerprint: str | None,
    initial_tail_bytes: int,
    retain_days: int,
    max_bytes: int,
    window_seconds: int,
    deadline_seconds: int,
) -> dict[str, object]:
    started_monotonic = time.monotonic()
    started_utc = utcnow()
    latch = store.load(store.latch, {})
    if active_latch(latch):
        raise RuntimeError(f"incident-latch-active:{latch.get('status')}")

    collection = collect(
        store,
        sources,
        config_fingerprint=config_fingerprint,
        initial_tail_bytes=initial_tail_bytes,
        retain_days=retain_days,
        max_bytes=max_bytes,
    )
    cutoff = utcnow() - dt.timedelta(seconds=window_seconds)
    diag = recent_rows(store, "diag", cutoff)
    host = recent_rows(store, "host", cutoff)
    cursor = store.load(store.cursor, {})
    missing = cursor.get("missing_sources", []) if isinstance(cursor, dict) else []

    incident_id = utcnow().strftime("%Y%m%dT%H%M%S.%fZ")
    tmp = store.incidents / f".{incident_id}.tmp"
    final = store.incidents / incident_id
    tmp.mkdir(parents=False, exist_ok=False)
    try:
        store.append_jsonl(tmp / "diag-15m.jsonl", diag)
        store.append_jsonl(tmp / "host-events-15m.jsonl", host)

        last_stages: dict[str, object] = {}
        interesting = {
            "MT_COMMAND_RX",
            "MT_COMMAND_DISPATCH",
            "MT_COMMAND_COMPLETE",
            "RESPONSE_QUEUED",
            "NPI_TX_FINISHED",
            "STARTUP_FROM_APP_ENTRY",
            "STARTUP_BDB_REQUEST",
            "STARTUP_BDB_RETURN",
            "STARTUP_SRSP_QUEUE",
            "BDB_DISPATCH",
            "BDB_RETURN",
        }
        for item in diag:
            rec = item.get("record")
            if isinstance(rec, dict):
                name = str(rec.get("kind_name", "UNKNOWN"))
                if name in interesting:
                    last_stages[name] = item

        elapsed = time.monotonic() - started_monotonic
        if elapsed > deadline_seconds:
            raise TimeoutError(f"capture-deadline:{elapsed:.3f}s")

        manifest = {
            "schema": 1,
            "incident_id": incident_id,
            "trigger_reason": trigger,
            "capture_started_utc": iso(started_utc),
            "capture_completed_utc": iso(),
            "window_seconds": window_seconds,
            "deadline_seconds": deadline_seconds,
            "diag_record_count": len(diag),
            "host_event_count": len(host),
            "latest_diagnostic_state": diag[-1] if diag else None,
            "last_successful_command_stages": last_stages,
            "collector_result": collection,
            "missing_sources": missing,
            "firmware_sha256": firmware_hash(store),
            "config_fingerprint": config_fingerprint,
            "observability_note": (
                "Missing telemetry is loss of observability, not proof of CPU failure."
            ),
        }
        store.atomic_json(tmp / "manifest.json", manifest)
        hashes = {
            item.name: sha256_file(item)
            for item in sorted(tmp.iterdir())
            if item.is_file()
        }
        store.atomic_json(tmp / "SHA256.json", hashes)
        Store.fsync_dir(tmp)
        os.replace(tmp, final)
        Store.fsync_dir(store.incidents)

        latch_value = {
            "schema": 1,
            "incident_id": incident_id,
            "bundle": str(final),
            "status": "captured",
            "captured_utc": iso(),
            "reset_used": False,
            "trigger_reason": trigger,
        }
        store.atomic_json(store.latch, latch_value)
        store.append_host_event("incident_captured", incident_id=incident_id, trigger=trigger)
        return {
            "ok": True,
            **latch_value,
            "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        }
    except Exception:
        try:
            for child in tmp.iterdir():
                child.unlink()
            tmp.rmdir()
        except OSError:
            pass
        raise


def update_latch(store: Store, expected: set[str], update: dict[str, object]) -> dict[str, object]:
    latch = store.load(store.latch, {})
    if not isinstance(latch, dict):
        raise RuntimeError("incident-latch-missing")
    status = str(latch.get("status"))
    if status not in expected:
        raise RuntimeError(f"incident-latch-state:{status}")
    latch.update(update)
    latch["updated_utc"] = iso()
    store.atomic_json(store.latch, latch)
    return latch


def authorize_reset(store: Store) -> dict[str, object]:
    latch = store.load(store.latch, {})
    if not isinstance(latch, dict) or latch.get("status") != "captured":
        raise RuntimeError("reset-requires-captured-incident")
    if latch.get("reset_used"):
        raise RuntimeError("automatic-reset-already-consumed")
    value = update_latch(
        store,
        {"captured"},
        {
            "status": "reset_authorized",
            "reset_used": True,
            "reset_authorized_utc": iso(),
        },
    )
    store.append_host_event("reset_authorized", incident_id=value.get("incident_id"))
    return value


def mark_recovering(store: Store) -> dict[str, object]:
    value = update_latch(
        store,
        {"reset_authorized"},
        {"status": "recovering", "recovery_started_utc": iso()},
    )
    store.append_host_event("recovery_started", incident_id=value.get("incident_id"))
    return value


def recovery_result(store: Store, *, success: bool, normal_traffic: bool) -> dict[str, object]:
    if not success or not normal_traffic:
        value = update_latch(
            store,
            {"reset_authorized", "recovering", "stabilizing"},
            {
                "status": "failed",
                "recovery_failed_utc": iso(),
                "normal_traffic_observed": bool(normal_traffic),
                "failure_reason": "verification-failed" if not success else "no-normal-traffic",
            },
        )
        store.append_host_event("recovery_failed", incident_id=value.get("incident_id"))
        return value

    stable_after = utcnow() + dt.timedelta(minutes=10)
    value = update_latch(
        store,
        {"reset_authorized", "recovering"},
        {
            "status": "stabilizing",
            "recovery_succeeded_utc": iso(),
            "normal_traffic_observed": True,
            "stable_after_utc": iso(stable_after),
        },
    )
    store.append_host_event(
        "recovery_stabilizing",
        incident_id=value.get("incident_id"),
        stable_after_utc=value.get("stable_after_utc"),
    )
    return value


def close_if_stable(store: Store, *, bridge_up: bool, normal_traffic: bool) -> dict[str, object]:
    latch = store.load(store.latch, {})
    if not isinstance(latch, dict) or latch.get("status") != "stabilizing":
        raise RuntimeError("incident-not-stabilizing")
    stable_after = parse_timestamp(str(latch.get("stable_after_utc", "")))
    if stable_after is None or utcnow() < stable_after:
        raise RuntimeError("stability-window-not-complete")
    if not bridge_up or not normal_traffic or not latch.get("normal_traffic_observed"):
        value = update_latch(
            store,
            {"stabilizing"},
            {
                "status": "failed",
                "recovery_failed_utc": iso(),
                "failure_reason": "stability-window-failed",
            },
        )
        store.append_host_event("stability_failed", incident_id=value.get("incident_id"))
        return value
    value = update_latch(store, {"stabilizing"}, {"status": "closed", "closed_utc": iso()})
    store.append_host_event("incident_closed", incident_id=value.get("incident_id"))
    return value


def manual_clear(store: Store, reason: str) -> dict[str, object]:
    value = store.load(store.latch, {})
    if not isinstance(value, dict):
        value = {}
    value.update(
        {
            "status": "cleared",
            "manual_clear_reason": reason,
            "manual_clear_utc": iso(),
        }
    )
    store.atomic_json(store.latch, value)
    store.append_host_event("incident_manual_clear", reason=reason)
    return value


def bool_arg(value: str) -> bool:
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected true/false")


def common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("T832_INCIDENT_ROOT", "/config/.private/t832-diag")),
    )
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--config-fingerprint")
    parser.add_argument("--initial-tail-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--retain-days", type=int, default=7)
    parser.add_argument("--max-bytes", type=int, default=1 << 30)


def main() -> int:
    ap = argparse.ArgumentParser()
    common_args(ap)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("collect")
    cap = sub.add_parser("capture")
    cap.add_argument("--trigger", required=True)
    cap.add_argument("--window-seconds", type=int, default=15 * 60)
    cap.add_argument("--deadline-seconds", type=int, default=30)
    sub.add_parser("authorize-reset")
    sub.add_parser("mark-recovering")
    rr = sub.add_parser("recovery-result")
    rr.add_argument("--success", type=bool_arg, required=True)
    rr.add_argument("--normal-traffic", type=bool_arg, required=True)
    close = sub.add_parser("close-if-stable")
    close.add_argument("--bridge-up", type=bool_arg, required=True)
    close.add_argument("--normal-traffic", type=bool_arg, required=True)
    clear = sub.add_parser("manual-clear")
    clear.add_argument("--reason", required=True)
    evt = sub.add_parser("host-event")
    evt.add_argument("--kind", required=True)
    evt.add_argument("--detail", default="")
    sub.add_parser("status")
    args = ap.parse_args()

    store = Store(args.root)
    sources = args.sources or DEFAULT_SOURCES
    try:
        if args.command == "collect":
            result = collect(
                store,
                sources,
                config_fingerprint=args.config_fingerprint,
                initial_tail_bytes=args.initial_tail_bytes,
                retain_days=args.retain_days,
                max_bytes=args.max_bytes,
            )
        elif args.command == "capture":
            result = capture(
                store,
                args.trigger,
                sources=sources,
                config_fingerprint=args.config_fingerprint,
                initial_tail_bytes=args.initial_tail_bytes,
                retain_days=args.retain_days,
                max_bytes=args.max_bytes,
                window_seconds=args.window_seconds,
                deadline_seconds=args.deadline_seconds,
            )
        elif args.command == "authorize-reset":
            result = authorize_reset(store)
        elif args.command == "mark-recovering":
            result = mark_recovering(store)
        elif args.command == "recovery-result":
            result = recovery_result(
                store,
                success=args.success,
                normal_traffic=args.normal_traffic,
            )
        elif args.command == "close-if-stable":
            result = close_if_stable(
                store,
                bridge_up=args.bridge_up,
                normal_traffic=args.normal_traffic,
            )
        elif args.command == "manual-clear":
            result = manual_clear(store, args.reason)
        elif args.command == "host-event":
            store.append_host_event(args.kind, detail=args.detail)
            result = {"ok": True, "kind": args.kind, "utc": iso()}
        else:
            result = store.load(store.latch, {"status": "none"})
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}:{exc}",
                    "command": args.command,
                    "utc": iso(),
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
