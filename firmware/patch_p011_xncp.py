#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PROFILE = {
    "schema": 1,
    "project": "Sonoff-Dongle-Max",
    "board": "SONOFF Dongle-M",
    "device": "EFR32MG24A420F1536IM48",
    "sdk": "2026.6.1",
    "emberznet": "9.1.1",
    "ezsp": 19,
    "transport": {"peripheral": "EUSART1", "baud": 115200, "flow_control": "none"},
    "resources": {
        "SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE": 512,
        "SL_ZIGBEE_BROADCAST_TABLE_SIZE": 64,
        "SL_ZIGBEE_KEY_TABLE_SIZE": 12,
        "SL_ZIGBEE_MULTICAST_TABLE_SIZE": 26,
        "SL_ZIGBEE_NEIGHBOR_TABLE_SIZE": 26,
        "SL_ZIGBEE_ROUTE_TABLE_SIZE": 254,
        "SL_ZIGBEE_SOURCE_ROUTE_TABLE_SIZE": 254,
        "SL_ZIGBEE_ADDRESS_TABLE_SIZE": 128,
        "SL_ZIGBEE_APS_UNICAST_MESSAGE_COUNT": 128,
        "SL_ZIGBEE_DISCOVERY_TABLE_SIZE": 16,
        "SL_ZIGBEE_MAX_END_DEVICE_CHILDREN": 64,
    },
}


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: patch_p011_xncp.py <already-P009 builder> <source-commit> <template-c>")
    root = Path(sys.argv[1]).resolve()
    source_commit = sys.argv[2].strip().lower()
    template = Path(sys.argv[3]).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise SystemExit("source commit must be a full 40-char SHA1")
    slcp = root / "src" / "zigbee_ncp" / "zigbee_ncp.slcp"
    if not slcp.is_file() or not template.is_file():
        raise SystemExit("unexpected builder/template layout")

    text = slcp.read_text(encoding="utf-8")
    for needle in (
        "SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE\n    value: 512",
        "SL_ZIGBEE_BROADCAST_TABLE_SIZE\n    value: 64",
        "SL_ZIGBEE_KEY_TABLE_SIZE\n    value: 12",
        "SL_ZIGBEE_MULTICAST_TABLE_SIZE\n    value: 26",
    ):
        if needle not in text:
            raise SystemExit(f"frozen P009 invariant missing before P011 patch: {needle}")

    if "  - id: zigbee_xncp\n" not in text:
        text = replace_once(
            text,
            "  - id: zigbee_ncp_uart_hardware\n",
            "  - id: zigbee_ncp_uart_hardware\n  - id: zigbee_xncp\n",
            "zigbee_xncp component",
        )
    text = replace_once(
        text,
        "source:\n  - path: main.c\n",
        "source:\n  - path: p011_identity.c\n  - path: main.c\n",
        "P011 source",
    )

    canonical = json.dumps(PROFILE, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    digest = hashlib.sha256(canonical).digest()
    hash_bytes = ", ".join(f"0x{x:02x}" for x in digest[:16])
    c = template.read_text(encoding="utf-8")
    c = c.replace("@@SOURCE_COMMIT@@", source_commit[:12]).replace("@@RESOURCE_HASH_BYTES@@", hash_bytes)
    if "@@" in c:
        raise SystemExit("unresolved identity template token")

    src = root / "src" / "zigbee_ncp"
    slcp.write_text(text, encoding="utf-8")
    (src / "p011_identity.c").write_text(c, encoding="utf-8")
    identity = {
        "schema": 1,
        "profile_id": "P011-IDENTITY-ON-P009",
        "source_commit": source_commit,
        "resource_profile": PROFILE,
        "canonical_resource_profile_sha256": digest.hex(),
        "wire_hash_prefix_hex": digest[:16].hex(),
        "wire_commit_prefix": source_commit[:12],
        "attestation_scope": "self-identification; not cryptographic remote attestation",
    }
    (src / "p011_identity_profile.json").write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"P011 identity-only XNCP applied: source={source_commit[:12]} profile_sha256={digest.hex()}")


if __name__ == "__main__":
    main()
