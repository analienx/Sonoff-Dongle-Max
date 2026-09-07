#!/usr/bin/env python3
"""Strict verifier for the P009 + stock rollback firmware bundle.

The source profile and the linked image are deliberately verified as separate
layers. A patched SLCP is not accepted as proof that the expected objects were
actually generated and linked into the NCP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
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

# These are linked-image facts independently measured on the approved pinned
# 2026.6.1/GCC14.2.1 build. They intentionally catch "source says X but ELF
# contains Y" regressions. Future deliberate toolchain changes must re-audit
# and update these assertions explicitly.
LINKED_SECTION_EXPECTED = {
    "stock": {".bss": 22_284, ".memory_manager_heap": 229_896},
    "p009": {".bss": 22_988, ".memory_manager_heap": 229_896},
}
LINKED_SYMBOL_EXPECTED = {
    "stock": {
        "rx_buffer_vcom": 128,
        "sli_zigbee_broadcast_table_data": 240,
        "sli_zigbee_incoming_aps_frame_counters": 8,
        "sli_zigbee_retry_queue": 320,
        "sli_zigbee_multicast_table": 104,
        "sli_zigbee_source_route_table_data": 1016,
        "sli_zigbee_route_table": 2040,
        "sli_zigbee_child_table_data": 1560,
    },
    "p009": {
        "rx_buffer_vcom": 512,
        "sli_zigbee_broadcast_table_data": 512,
        "sli_zigbee_incoming_aps_frame_counters": 52,
        "sli_zigbee_retry_queue": 320,
        "sli_zigbee_multicast_table": 104,
        "sli_zigbee_source_route_table_data": 1016,
        "sli_zigbee_route_table": 2040,
        "sli_zigbee_child_table_data": 1560,
    },
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


def _readelf(path: Path, flag: str) -> str:
    try:
        cp = subprocess.run(["readelf", flag, str(path)], text=True, capture_output=True, check=True)
    except FileNotFoundError:
        die("readelf is required for linked-image verification")
    except subprocess.CalledProcessError as exc:
        die(f"readelf {flag} failed for {path}: {(exc.stderr or '').strip()}")
    return cp.stdout


def readelf_sections(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    # readelf -SW columns: [Nr] Name Type Address Off Size ES Flg Lk Inf Al
    rx = re.compile(r"^\s*\[\s*\d+\]\s+(\S+)\s+\S+\s+[0-9a-fA-F]+\s+[0-9a-fA-F]+\s+([0-9a-fA-F]+)\s+", re.MULTILINE)
    for name, size_hex in rx.findall(_readelf(path, "-SW")):
        out[name] = int(size_hex, 16)
    return out


def readelf_symbols(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    # Size is decimal in GNU readelf symbol output.
    rx = re.compile(r"^\s*\d+:\s+[0-9a-fA-F]+\s+(\d+)\s+\S+\s+\S+\s+\S+\s+\S+\s+(.+?)\s*$", re.MULTILINE)
    for size, name in rx.findall(_readelf(path, "-sW")):
        # Strip a possible ELF version suffix while preserving ordinary names.
        clean = name.split("@", 1)[0]
        if clean:
            out[clean] = int(size)
    return out


def linked_evidence(stock_out: Path, p009_out: Path) -> dict[str, object]:
    report: dict[str, object] = {"validated": False, "sections": {}, "symbols": {}}
    for variant, path in (("stock", stock_out), ("p009", p009_out)):
        sections = readelf_sections(path)
        symbols = readelf_symbols(path)
        expected_sections = LINKED_SECTION_EXPECTED[variant]
        expected_symbols = LINKED_SYMBOL_EXPECTED[variant]
        section_actual = {name: sections.get(name) for name in expected_sections}
        symbol_actual = {name: symbols.get(name) for name in expected_symbols}
        bad_sections = {k: (expected_sections[k], section_actual.get(k)) for k in expected_sections if section_actual.get(k) != expected_sections[k]}
        bad_symbols = {k: (expected_symbols[k], symbol_actual.get(k)) for k in expected_symbols if symbol_actual.get(k) != expected_symbols[k]}
        if bad_sections:
            die(f"{variant} linked section mismatch: {bad_sections}")
        if bad_symbols:
            die(f"{variant} linked symbol-size mismatch: {bad_symbols}")
        report["sections"][variant] = section_actual
        report["symbols"][variant] = symbol_actual
    s_bss = report["sections"]["stock"][".bss"]
    p_bss = report["sections"]["p009"][".bss"]
    if p_bss - s_bss != 704:
        die(f"linked .bss delta must be 704 bytes, got {p_bss - s_bss}")
    report["bss_delta_bytes"] = 704
    report["memory_manager_heap_delta_bytes"] = 0
    report["validated"] = True
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p009-dir", type=Path, required=True)
    ap.add_argument("--stock-dir", type=Path, required=True)
    ap.add_argument("--p009-slcp", type=Path, required=True, help="patched source-profile input; not proof of linked output")
    ap.add_argument("--stock-slcp", type=Path, required=True, help="stock source-profile input; not proof of linked output")
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--source-commit", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        die("--source-commit must be an exact 40-character Git commit")

    p_profile = profile(args.p009_slcp)
    s_profile = profile(args.stock_slcp)
    validate_profile(p_profile, P009_ONLY)
    validate_profile(s_profile, STOCK_ONLY)
    changed = {k for k in p_profile if p_profile[k] != s_profile[k]}
    allowed = set(P009_ONLY)
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

    linked = linked_evidence(s_art["out"], p_art["out"])
    report = {
        "schema": 2,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"repository": "analienx/Sonoff-Dongle-Max", "repository_commit": args.source_commit},
        "builder": {"repository": "Nerivec/silabs-firmware-builder", "commit": BUILDER_PIN},
        "firmware": {"emberznet": EMBER, "ezsp": 19, "transport": transport},
        "source_profile_evidence": {
            "scope": "SLCP/source inputs only; linked_evidence is authoritative for measured object sizes",
            "p009": p_profile,
            "rollback_stock": s_profile,
        },
        "p009": {"profile": p_profile, "artifacts": {k: artifact_record(v) for k, v in p_art.items()}},
        "rollback_stock": {"profile": s_profile, "artifacts": {k: artifact_record(v) for k, v in s_art.items()}},
        "allowed_profile_differences": sorted(allowed),
        "linked_evidence": linked,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
