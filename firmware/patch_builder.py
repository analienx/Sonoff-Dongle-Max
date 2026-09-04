#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

PINNED_BUILDER = "858c34b0eb6f53a2e0c89455ea489ceaa62d58db"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def require(pattern: str, text: str, label: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE) is None:
        raise SystemExit(f"required profile invariant missing: {label}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_builder.py <silabs-firmware-builder checkout>")

    root = Path(sys.argv[1]).resolve()
    slcp = root / "src" / "zigbee_ncp" / "zigbee_ncp.slcp"
    manifest = root / "manifests" / "sonoff" / "sonoff_dongle-m_zigbee_ncp.yaml"
    if not slcp.is_file() or not manifest.is_file():
        raise SystemExit("unexpected builder layout")

    original = slcp.read_text(encoding="utf-8")
    text = original
    text = replace_once(text, "  - name: SL_ZIGBEE_BROADCAST_TABLE_SIZE\n    value: 30\n", "  - name: SL_ZIGBEE_BROADCAST_TABLE_SIZE\n    value: 64\n", "broadcast table")
    text = replace_once(text, "  - name: SL_ZIGBEE_KEY_TABLE_SIZE\n    value: 1\n", "  - name: SL_ZIGBEE_KEY_TABLE_SIZE\n    value: 12\n", "key table")

    invariants = {
        "multicast=26": r"- name: SL_ZIGBEE_MULTICAST_TABLE_SIZE\n\s+value: 26",
        "discovery xg24=16": r"- name: SL_ZIGBEE_DISCOVERY_TABLE_SIZE\n\s+value: 16\n\s+condition: \[\"device_generic_family_efr32xg24\"\]",
        "neighbor=26": r"- name: SL_ZIGBEE_NEIGHBOR_TABLE_SIZE\n\s+value: 26",
        "binding=32": r"- name: SL_ZIGBEE_BINDING_TABLE_SIZE\n\s+value: 32",
        "route xg24=254": r"- name: SL_ZIGBEE_ROUTE_TABLE_SIZE\n\s+value: 254\n\s+condition: \[\"device_generic_family_efr32xg24\"\]",
        "source-route xg24=254": r"- name: SL_ZIGBEE_SOURCE_ROUTE_TABLE_SIZE\n\s+value: 254\n\s+condition: \[\"device_generic_family_efr32xg24\"\]",
        "address xg24=128": r"- name: SL_ZIGBEE_ADDRESS_TABLE_SIZE\n\s+value: 128\n\s+condition: \[\"device_generic_family_efr32xg24\"\]",
        "APS unicast xg24=128": r"- name: SL_ZIGBEE_APS_UNICAST_MESSAGE_COUNT\n\s+value: 128\n\s+condition: \[\"device_generic_family_efr32xg24\"\]",
        "children xg24=64": r"- name: SL_ZIGBEE_MAX_END_DEVICE_CHILDREN\n\s+value: 64\n\s+condition: \[\"device_generic_family_efr32xg24\"\]",
        "duplicate rejection xg24=64": r"- name: SL_ZIGBEE_APS_DUPLICATE_REJECTION_MAX_ENTRIES\n\s+value: 64\n\s+condition: \[\"device_generic_family_efr32xg24\"\]",
        "huge packet heap xg24": r"- name: SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE\n\s+value: SL_ZIGBEE_HUGE_PACKET_BUFFER_HEAP\n\s+condition: \[\"device_generic_family_efr32xg24\"\]",
        "broadcast=64": r"- name: SL_ZIGBEE_BROADCAST_TABLE_SIZE\n\s+value: 64",
        "key=12": r"- name: SL_ZIGBEE_KEY_TABLE_SIZE\n\s+value: 12",
    }
    for label, pattern in invariants.items():
        require(pattern, text, label)

    m = manifest.read_text(encoding="utf-8")
    manifest_invariants = {
        "MG24 part": r"device: EFR32MG24A420F1536IM48",
        "SDK 2026.6.1": r"sdk: \"simplicity_sdk:2026\.6\.1\"",
        "115200": r"SL_IOSTREAM_EUSART_VCOM_BAUDRATE: 115200",
        "no flow control": r"SL_IOSTREAM_EUSART_VCOM_FLOW_CONTROL_TYPE: SL_IOSTREAM_EUSART_UART_FLOW_CTRL_NONE",
        "EUSART1": r"SL_IOSTREAM_EUSART_VCOM_PERIPHERAL: EUSART1",
    }
    for label, pattern in manifest_invariants.items():
        require(pattern, m, label)
    if text == original:
        raise SystemExit("patch produced no change")
    slcp.write_text(text, encoding="utf-8")
    print("P009 profile applied successfully")
    print("  broadcast table: 30 -> 64")
    print("  key table:        1 -> 12")
    print("  all other MG24 resource/transport invariants verified")


if __name__ == "__main__":
    main()
