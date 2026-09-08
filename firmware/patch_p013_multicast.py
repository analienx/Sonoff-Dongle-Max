#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


def require(pattern: str, text: str, label: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE) is None:
        raise SystemExit(f"P013 prerequisite missing: {label}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_p013_multicast.py <already-P009 builder checkout>")
    root = Path(sys.argv[1]).resolve()
    slcp = root / "src" / "zigbee_ncp" / "zigbee_ncp.slcp"
    if not slcp.is_file():
        raise SystemExit("unexpected builder layout")

    text = slcp.read_text(encoding="utf-8")
    prerequisites = {
        "RX512": r"- name: SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE\n\s+value: 512",
        "BTT64": r"- name: SL_ZIGBEE_BROADCAST_TABLE_SIZE\n\s+value: 64",
        "KEY12": r"- name: SL_ZIGBEE_KEY_TABLE_SIZE\n\s+value: 12",
        "MCAST26": r"- name: SL_ZIGBEE_MULTICAST_TABLE_SIZE\n\s+value: 26",
    }
    for label, pattern in prerequisites.items():
        require(pattern, text, label)

    old = "  - name: SL_ZIGBEE_MULTICAST_TABLE_SIZE\n    value: 26\n"
    new = "  - name: SL_ZIGBEE_MULTICAST_TABLE_SIZE\n    value: 32\n"
    if text.count(old) != 1:
        raise SystemExit(f"P013 multicast patch expected exactly one stock value, got {text.count(old)}")
    text = text.replace(old, new, 1)
    slcp.write_text(text, encoding="utf-8")
    print("P013 applied on top of frozen P009: multicast table 26 -> 32")


if __name__ == "__main__":
    main()
