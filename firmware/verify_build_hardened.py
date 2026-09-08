#!/usr/bin/env python3
"""Compatibility-hardened launcher for the strict P009 linked-image verifier.

The pinned builder has emitted the EUSART condition in multiple equivalent YAML
serializations over time. This launcher replaces only that source-profile parser;
all binary/linker/profile assertions continue to come from verify_build.py.
"""
from __future__ import annotations

import re

import verify_build as core


def _slcp_named_blocks(text: str, name: str) -> list[str]:
    header = re.compile(rf"(?m)^\s*-\s+name:\s*['\"]?{re.escape(name)}['\"]?\s*(?:#.*)?$")
    any_header = re.compile(r"(?m)^\s*-\s+name:\s*")
    blocks: list[str] = []
    for match in header.finditer(text):
        nxt = any_header.search(text, match.end())
        blocks.append(text[match.start() : nxt.start() if nxt else len(text)])
    return blocks


def _condition_tokens(block: str) -> set[str]:
    match = re.search(r"(?m)^\s*condition:\s*(?P<inline>[^#\n]*)", block)
    if not match:
        return set()
    inline = match.group("inline").strip()
    if inline:
        return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", inline))

    tokens: set[str] = set()
    for raw in block[match.end() :].splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*\s*:", stripped):
            break
        item = re.match(r"-\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*(?:#.*)?$", stripped)
        if item:
            tokens.add(item.group(1))
            continue
        break
    return tokens


def extract_eusart_rx_buffer(text: str) -> int:
    name = "SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE"
    matches: list[int] = []
    for block in _slcp_named_blocks(text, name):
        if "iostream_eusart" not in _condition_tokens(block):
            continue
        value = re.findall(r"(?m)^\s*value:\s*['\"]?([0-9]+)['\"]?\s*(?:#.*)?$", block)
        if len(value) != 1:
            core.die(f"{name}: EUSART entry must contain exactly one numeric value, got {value}")
        matches.append(int(value[0]))
    if len(matches) != 1:
        core.die(f"{name}: expected exactly one EUSART-conditioned value, got {matches}")
    return matches[0]


def main() -> None:
    core.extract_eusart_rx_buffer = extract_eusart_rx_buffer
    core.main()


if __name__ == "__main__":
    main()
