#!/usr/bin/env python3
"""Strict verifier for the P009 + stock rollback firmware bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

BUILDER_PIN = "858c34b0eb6f53a2e0c89455ea489ceaa62d58db"
SDK = "2026.6.1"
EMBER = "9.1.1"
DEVICE = "EFR32MG24A420F1536IM48"
COMMON_PROFILE = {
    "SL_ZIGBEE_MULTICAST_TABLE_SIZE": 26,
    "SL_ZIGBEE_DISCOVERY_TABLE_SIZE": 16,
    "SL_ZIGBEE_NEIGHBOR_TABLE_SIZE": 26,
    "SL_ZIGBEE_BINDING_TABLE_SIZE": 32,
    "SL_ZIGBEE_ROUTE_TABLE_SIZE": 254,
    "SL_ZIGBEE_SOURCE_ROUTE_TABLE_SIZE": 254,
    "SL_ZIGBEE_ADDRESS_TABLE_SIZE": 128,
    "SL_ZIGBEE_APS_UNICAST_MESSAGE_COUNT": 128,
    "SL_ZIGBEE_MAX_END_DEVICE_CHILDREN": 64,
    "SL_ZIGBEE_APS_DUPLICATE_REJECTION_MAX_ENTRIES": 64,
}
P009_ONLY = {
    "SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE": 512,
    "SL_ZIGBEE_BROADCAST_TABLE_SIZE": 64,
    "SL_ZIGBEE_KEY_TABLE_SIZE": 12,
}
STOCK_ONLY = {
    "SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE": 128,
    "SL_ZIGBEE_BROADCAST_TABLE_SIZE": 30,
    "SL_ZIGBEE_KEY_TABLE_SIZE": 1,
}


def die(message: str) -> None:
    raise SystemExit(f"P009 verify: {message}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def single_artifact(directory: Path, suffix: str) -> Path:
    matches = sorted(directory.glob(f"*{suffix}"))
    if len(matches) != 1:
        die(f"{directory}: expected exactly one {suffix}, got {len(matches)}")
    if matches[0].stat().st_size < 10_000:
        die(f"{matches[0]} is implausibly small")
    return matches[0]


def extract_value(text: str, name: str, xg24: bool = False) -> int:
    if xg24:
        pat = rf"- name: {re.escape(name)}\s*\n\s+value: ([0-9]+)\s*\n\s+condition: \[\"device_generic_family_efr32xg24\"\]"
    else:
        pat = rf"- name: {re.escape(name)}\s*\n\s+value: ([0-9]+)"
    matches = re.findall(pat, text)
    if len(matches) != 1:
        die(f"{name}: expected one {'xg24 ' if xg24 else ''}value, got {matches}")
    return int(matches[0])


def extract_eusart_rx_buffer(text: str) -> int:
    pat = r"- name: SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE\s*\n\s+value: ([0-9]+)\s*\n\s+condition:\s*\n\s+- iostream_eusart"
    matches = re.findall(pat, text)
    if len(matches) != 1:
        die(f"SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE: expected one EUSART value, got {matches}")
    return int(matches[0])


def profile(slcp: Path) -> dict[str, int | str]:
    text = slcp.read_text(encoding="utf-8")
    out: dict[str, int | str] = {}
    global_names = {
        "SL_ZIGBEE_MULTICAST_TABLE_SIZE",
        "SL_ZIGBEE_NEIGHBOR_TABLE_SIZE",
        "SL_ZIGBEE_BINDING_TABLE_SIZE",
        "SL_ZIGBEE_BROADCAST_TABLE_SIZE",
        "SL_ZIGBEE_KEY_TABLE_SIZE",
    }
    for name in (*COMMON_PROFILE, "SL_ZIGBEE_BROADCAST_TABLE_SIZE", "SL_ZIGBEE_KEY_TABLE_SIZE"):
        out[name] = extract_value(text, name, xg24=name not in global_names)
    out["SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE"] = extract_eusart_rx_buffer(text)
    heap_pat = r"- name: SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE\s*\n\s+value: (SL_ZIGBEE_HUGE_PACKET_BUFFER_HEAP)\s*\n\s+condition: \[\"device_generic_family_efr32xg24\"\]"
    m = re.findall(heap_pat, text)
    if m != ["SL_ZIGBEE_HUGE_PACKET_BUFFER_HEAP"]:
        die("xg24 HUGE packet heap invariant missing")
    out["SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE"] = m[0]
    return out


def validate_profile(actual: dict[str, int | str], expected_delta: dict[str, int]) -> None:
    expected: dict[str, int | str] = {**COMMON_PROFILE, **expected_delta}
    expected["SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE"] = "SL_ZIGBEE_HUGE_PACKET_BUFFER_HEAP"
    if actual != expected:
        missing = {k: v for k, v in expected.items() if actual.get(k) != v}
        die(f"profile mismatch: {missing}")


def validate_manifest(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    required = {
        "device": rf"^device:\s*{DEVICE}\s*$",
        "sdk": rf'^sdk:\s*"simplicity_sdk:{re.escape(SDK)}"\s*$',
        "baud": r"^\s*SL_IOSTREAM_EUSART_VCOM_BAUDRATE:\s*115200\s*$",
        "flow": r"^\s*SL_IOSTREAM_EUSART_VCOM_FLOW_CONTROL_TYPE:\s*SL_IOSTREAM_EUSART_UART_FLOW_CTRL_NONE\s*$",
        "eusart": r"^\s*SL_IOSTREAM_EUSART_VCOM_PERIPHERAL:\s*EUSART1\s*$",
    }
    for label, pat in required.items():
        if not re.search(pat, text, flags=re.MULTILINE):
            die(f"manifest invariant missing: {label}")
    return {"device": DEVICE, "sdk": SDK, "baudrate": 115200, "flow_control": "none", "peripheral": "EUSART1"}


def artifact_record(path: Path) -> dict[str, object]:
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p009-dir", type=Path, required=True)
    ap.add_argument("--stock-dir", type=Path, required=True)
    ap.add_argument("--p009-slcp", type=Path, required=True)
    ap.add_argument("--stock-slcp", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    p_profile = profile(args.p009_slcp)
    s_profile = profile(args.stock_slcp)
    validate_profile(p_profile, P009_ONLY)
    validate_profile(s_profile, STOCK_ONLY)
    changed = {k for k in p_profile if p_profile[k] != s_profile[k]}
    allowed = {
        "SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE",
        "SL_ZIGBEE_BROADCAST_TABLE_SIZE",
        "SL_ZIGBEE_KEY_TABLE_SIZE",
    }
    if changed != allowed:
        die(f"P009 vs stock resource differences must be exactly {sorted(allowed)}, got {sorted(changed)}")

    transport = validate_manifest(args.manifest)
    p_art = {ext[1:]: single_artifact(args.p009_dir, ext) for ext in (".gbl", ".hex", ".out")}
    s_art = {ext[1:]: single_artifact(args.stock_dir, ext) for ext in (".gbl", ".hex", ".out")}
    for variant, artifacts in (("p009", p_art), ("stock", s_art)):
        for path in artifacts.values():
            low = path.name.lower()
            for token in ("sonoff_dongle-m_zigbee_ncp", "115200", "no_flow"):
                if token not in low:
                    die(f"{variant} artifact filename lacks {token}: {path.name}")
    if sha256(p_art["gbl"]) == sha256(s_art["gbl"]):
        die("P009 GBL is byte-identical to stock rollback GBL")

    report = {
        "schema": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "builder": {"repository": "Nerivec/silabs-firmware-builder", "commit": BUILDER_PIN},
        "firmware": {"emberznet": EMBER, "ezsp": 19, "transport": transport},
        "p009": {"profile": p_profile, "artifacts": {k: artifact_record(v) for k, v in p_art.items()}},
        "rollback_stock": {"profile": s_profile, "artifacts": {k: artifact_record(v) for k, v in s_art.items()}},
        "allowed_profile_differences": sorted(allowed),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
