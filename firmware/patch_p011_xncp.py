#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: patch_p011_xncp.py <builder> <source-commit> <template-c>")
    root = Path(sys.argv[1]).resolve()
    source_commit = sys.argv[2].strip().lower()
    template = Path(sys.argv[3]).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise SystemExit("source commit must be a full 40-char SHA1")
    slcp = root / "src" / "zigbee_ncp" / "zigbee_ncp.slcp"
    if not slcp.is_file() or not template.is_file():
        raise SystemExit("unexpected builder/template layout")

    text = slcp.read_text(encoding="utf-8")
    # P011 is derived from already-patched P009 and must not alter its four resources.
    for needle in (
        "SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE\n    value: 512",
        "SL_ZIGBEE_BROADCAST_TABLE_SIZE\n    value: 64",
        "SL_ZIGBEE_KEY_TABLE_SIZE\n    value: 12",
        "SL_ZIGBEE_MULTICAST_TABLE_SIZE\n    value: 32",
    ):
        if needle not in text:
            raise SystemExit(f"P009 invariant missing before P011 patch: {needle}")

    if "  - id: zigbee_xncp\n" not in text:
        text = replace_once(text, "  - id: zigbee_ncp_uart_hardware\n", "  - id: zigbee_ncp_uart_hardware\n  - id: zigbee_xncp\n", "zigbee_xncp component")
    text = replace_once(text, "source:\n  - path: main.c\n", "source:\n  - path: p011_identity.c\n  - path: main.c\n", "P011 source")

    # Hash the semantic resource profile after enabling XNCP but before embedding identity.
    canonical = "\n".join(line.rstrip() for line in text.splitlines()).encode()
    profile_hash = hashlib.sha256(canonical).digest()
    hash_bytes = ", ".join(f"0x{x:02x}" for x in profile_hash[:16])
    c = template.read_text(encoding="utf-8")
    c = c.replace("@@SOURCE_COMMIT@@", source_commit[:12]).replace("@@RESOURCE_HASH_BYTES@@", hash_bytes)
    if "@@" in c:
        raise SystemExit("unresolved identity template token")

    slcp.write_text(text, encoding="utf-8")
    (root / "src" / "zigbee_ncp" / "p011_identity.c").write_text(c, encoding="utf-8")
    print(f"P011 identity-only XNCP applied: source={source_commit[:12]} profile_sha256={profile_hash.hex()}")


if __name__ == "__main__":
    main()
