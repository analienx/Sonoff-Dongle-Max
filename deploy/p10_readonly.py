"""Isolated CC2674P10/ZNP inspection. No flash, reset, NV, network or pairing commands."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SOF = 0xFE
ALLOWED = {(0x21, 0x01), (0x21, 0x02)}  # SYS_PING, SYS_VERSION ONLY


def frame(cmd0: int, cmd1: int, data: bytes = b"") -> bytes:
    if (cmd0, cmd1) not in ALLOWED or data:
        raise ValueError("Unapproved ZNP command or payload")
    body = bytes([0, cmd0, cmd1])
    checksum = 0
    for value in body:
        checksum ^= value
    return bytes([SOF]) + body + bytes([checksum])


def receive(ser, command: tuple[int, int], deadline: float) -> bytes:
    """Ignore unrelated asynchronous frames; reject bad FCS and truncated frames."""
    expected = (command[0] | 0x40, command[1])
    while time.monotonic() < deadline:
        if ser.read(1) != bytes([SOF]):
            continue
        header = ser.read(3)
        if len(header) != 3:
            continue
        count, cmd0, cmd1 = header
        tail = ser.read(count + 1)
        if len(tail) != count + 1:
            continue
        fcs = 0
        for value in header + tail:
            fcs ^= value
        if fcs:
            continue
        if (cmd0, cmd1) == expected:
            return tail[:-1]
    raise TimeoutError(f"No valid SRSP for {command[0]:02x}/{command[1]:02x}")


def version_details(data: bytes) -> dict:
    if len(data) not in (5, 9):
        raise ValueError("Unexpected or truncated SYS_VERSION response length")
    result = dict(zip(("transport_rev", "product", "major", "minor", "maintenance"), data[:5]))
    if len(data) >= 9:
        result["revision_raw_uint32"] = int.from_bytes(data[5:9], "little")
    result["version_payload_length"] = len(data)
    return result


def ports() -> list[dict]:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise RuntimeError("Install pyserial: py -3 -m pip install pyserial") from exc
    return [{"port": p.device, "description": p.description, "vid": p.vid, "pid": p.pid,
             "manufacturer": p.manufacturer} for p in list_ports.comports()]


def inspect(port: str, baud: int, production_port: str | None, expected_vid: int | None = None, expected_pid: int | None = None) -> dict:
    if not re.fullmatch(r"COM\d+|/dev/(?:serial/by-id/[A-Za-z0-9_.:-]+|ttyUSB\d+|ttyACM\d+)", port, re.I):
        raise ValueError("Only an explicit local USB serial device is allowed")
    if production_port and port.lower() == production_port.lower():
        raise ValueError("Refusing the named production coordinator port")
    if expected_vid is None or expected_pid is None:
        raise ValueError("Explicit VID/PID from prior USB enumeration are required")
    matches = [p for p in ports() if p["port"].lower() == port.lower()]
    if len(matches) != 1 or matches[0]["vid"] != expected_vid or matches[0]["pid"] != expected_pid:
        raise ValueError("Selected USB port missing or VID/PID mismatch; refusing to open")
    import serial
    ser = serial.Serial(port=None, baudrate=baud, timeout=0.4, write_timeout=1)
    ser.port = port
    ser.dtr = False
    ser.rts = False
    try:
        ser.open()
        outcome = {}
        for name, command in (("ping", (0x21, 0x01)), ("version", (0x21, 0x02))):
            ser.write(frame(*command))
            ser.flush()
            payload = receive(ser, command, time.monotonic() + 3)
            if name == "ping":
                if len(payload) != 2:
                    raise ValueError("Invalid SYS_PING response length")
                outcome["capability_mask"] = int.from_bytes(payload, "little")
            else:
                outcome["firmware"] = version_details(payload)
        return {"probe": "ZNP read-only ping/version", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "port": port, "baud": baud, "result": outcome,
                "neighbor_capacity": "UNKNOWN: not exposed by SYS_VERSION",
                "tclk_capacity": "UNKNOWN: not exposed by SYS_VERSION"}
    finally:
        ser.close()


def save_exclusive(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(obj, stream, indent=2, sort_keys=True)
        stream.write("\n")


def artifact(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": sha.hexdigest(),
            "compiled_neighbor_capacity": "UNKNOWN: checksum does not reveal table layout",
            "compiled_tclk_capacity": "UNKNOWN: checksum does not reveal table layout"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("ports", help="List serial-port metadata, without opening ports")
    usb = sub.add_parser("inspect", help="Only two non-mutating ZNP commands on a separate host")
    usb.add_argument("--port", required=True)
    usb.add_argument("--baud", type=int, choices=(115200, 460800, 921600), default=115200)
    usb.add_argument("--production-port", help="Refuse this production port")
    usb.add_argument("--vid", type=lambda x: int(x, 0), required=True, help="USB VID shown by ports, e.g. 0x1A86")
    usb.add_argument("--pid", type=lambda x: int(x, 0), required=True, help="USB PID shown by ports")
    usb.add_argument("--isolated-host-confirmed", action="store_true", required=True)
    usb.add_argument("--out", type=Path, help="Create exclusive private JSON result; never overwrite")
    image = sub.add_parser("artifact", help="Offline SHA-256 fingerprint of downloaded exact firmware")
    image.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "ports":
            result = {"ports": ports()}
        elif args.action == "artifact":
            result = artifact(args.file)
        else:
            if not args.isolated_host_confirmed:
                raise ValueError("Use a separate host, verify this is the new P10, then set --isolated-host-confirmed")
            if args.out and args.out.exists():
                raise FileExistsError(args.out)
            result = inspect(args.port, args.baud, args.production_port, args.vid, args.pid)
            if args.out:
                save_exclusive(args.out, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
        print(f"P10_PREFLIGHT_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
