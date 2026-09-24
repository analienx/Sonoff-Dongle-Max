"""Measure factory-provisioned P10 Z-Stack TCLK NV slots using LENGTH-ONLY ZNP.

Only isolated, never-commissioned MR4U radio; NO NV reads, key bytes, writes,
network creation, reset, bootloader, or production-host access. This proves
provisioned NV slots, NOT MAX_NEIGHBOR_ENTRIES or migration reliability.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path
from p10_readonly import ports, receive, version_details

VID, PID = 0x303A, 0x4002
TCLK_SYS_ID, TCLK_ITEM_ID = 1, 4


def readonly_frame(cmd0: int, cmd1: int, data: bytes = b"") -> bytes:
    if (cmd0, cmd1) not in ((0x21, 0x01), (0x21, 0x02), (0x27, 0x00), (0x21, 0x32)):
        raise ValueError("Non-read-only ZNP command refused")
    if (cmd0, cmd1) == (0x21, 0x32):
        if len(data) != 5 or data[:3] != bytes((TCLK_SYS_ID, TCLK_ITEM_ID, 0)):
            raise ValueError("Only extended Z-Stack TCLK item length may be queried")
    elif data:
        raise ValueError("Non-empty payload for read-only version/state request")
    body = bytes((len(data), cmd0, cmd1)) + data
    fcs = 0
    for byte in body:
        fcs ^= byte
    return b"\xfe" + body + bytes((fcs,))


def query(ser, cmd0: int, cmd1: int, payload=b"", timeout=2.5) -> bytes:
    ser.write(readonly_frame(cmd0, cmd1, payload))
    ser.flush()
    return receive(ser, (cmd0, cmd1), time.monotonic() + timeout)


def validated_idle_state(payload: bytes) -> None:
    # UTIL_GET_DEVICE_INFO: status, 8-byte IEEE (never print), short NWK,
    # device type, device state, count, then 2-byte associated NWK addresses.
    if len(payload) < 14 or len(payload) != 14 + 2 * payload[13]:
        raise ValueError("Malformed UTIL_GET_DEVICE_INFO response")
    if payload[0] != 0 or payload[12] != 0 or payload[13] != 0:
        raise ValueError("Radio not idle/uncommissioned: refuse exhaustive NV probe")


def scan_lengths(ser, end: int) -> dict:
    values = []
    for index in range(end + 1):
        data = bytes((TCLK_SYS_ID, TCLK_ITEM_ID, 0, index & 255, index >> 8))
        response = query(ser, 0x21, 0x32, data)
        if len(response) != 4:
            raise ValueError("Expected exact 4-byte NV_LENGTH response on this firmware")
        values.append(int.from_bytes(response, "little"))
    if any(value not in (0, 20) for value in values):
        raise ValueError("Unexpected TCLK record length; capacity not established")
    count = sum(value == 20 for value in values)
    complete = values == [20] * count + [0] * (len(values) - count)
    if not complete:
        raise ValueError("Non-contiguous TCLK NV lengths; capacity not established")
    return {"provisioned_tclk_nv_slots": count,
            "last_present_index": count - 1 if count else None,
            "first_missing_index": count if count <= end else None,
            "scanned_indices": len(values),
            "upper_boundary_observed": count <= end,
            "meets_100_slot_target": count >= 100,
            "neighbor_table_capacity": "NOT_MEASURED",
            "aps_security_manager_capacity": "NOT_MEASURED",
            "proves_network_migration": False}


def inspect(port: str, serial_number: str, location: str, revision: int, end: int) -> dict:
    if not re.fullmatch(r"COM\d+|/dev/tty(?:USB|ACM)\d+", port):
        raise ValueError("Only an explicit local USB serial port is accepted")
    matches = [p for p in ports() if p["port"].lower() == port.lower()]
    if len(matches) != 1 or any((matches[0]["vid"] != VID, matches[0]["pid"] != PID,
                                 matches[0]["serial_number"] != serial_number,
                                 matches[0]["location"] != location)):
        raise ValueError("Exact USB identity mismatch: port not opened")
    import serial
    ser = serial.Serial(port=None, baudrate=115200, timeout=0.4, write_timeout=1)
    ser.port = port
    ser.dtr = False
    ser.rts = False
    try:
        ser.open()
        ping = query(ser, 0x21, 0x01)
        if len(ping) != 2:
            raise ValueError("Malformed SYS_PING response")
        version = version_details(query(ser, 0x21, 0x02))
        if version.get("product") != 1 or version.get("revision_raw_uint32") != revision:
            raise ValueError("Not the pinned P10 Z-Stack firmware revision")
        validated_idle_state(query(ser, 0x27, 0x00))
        data = scan_lengths(ser, end)
        validated_idle_state(query(ser, 0x27, 0x00))
        after = version_details(query(ser, 0x21, 0x02))
        if after != version:
            raise ValueError("Firmware changed during NV length scan")
        data.update({"hardware":"SMLIGHT MR4U P10 USB interface, not an attested silicon ID",
                     "znp_revision": version["revision_raw_uint32"],
                     "znp_product": version["product"],
                     "proof_kind":"actual-running-radio length-only NV allocation",
                     "firmware_sha256":"UNKNOWN; no image readback",
                     "read_only_commands":"SYS_PING, SYS_VERSION, UTIL_GET_DEVICE_INFO, SYS_NV_LENGTH",
                     "no_key_material_read": True,
                     "runtime_state":"idle before and after, zero associated devices",
                     "usable_active_keys":"UNTESTED; provisioned records not authentication tests"})
        return data
    finally:
        ser.close()

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--serial-number", required=True)
    parser.add_argument("--usb-location", required=True)
    parser.add_argument("--expected-revision", required=True, type=int)
    parser.add_argument("--end-index", type=int, default=420)
    parser.add_argument("--isolated-idle-p10-confirmed", action="store_true", required=True)
    parser.add_argument("--out", type=Path, help="Private, create-only sanitized output")
    args = parser.parse_args(argv)
    try:
        if not args.isolated_idle_p10_confirmed or not 400 <= args.end_index <= 1024:
            raise ValueError("Confirm isolated idle radio and scan >=400 up to 1024 indices")
        if args.out and args.out.exists():
            raise FileExistsError(args.out)
        result = inspect(args.port, args.serial_number, args.usb_location,
                         args.expected_revision, args.end_index)
        if args.out:
            with args.out.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2, sort_keys=True)
                handle.write("\n")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["upper_boundary_observed"] else 3
    except (OSError, RuntimeError, ValueError, TimeoutError, TypeError) as exc:
        print("P10_NV_EVIDENCE_BLOCKED: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
