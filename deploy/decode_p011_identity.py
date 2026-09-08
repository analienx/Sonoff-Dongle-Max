#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json


def decode_identity(payload: bytes) -> dict:
    if len(payload) != 34:
        raise ValueError(f"expected 34-byte P011 identity response, got {len(payload)}")
    if payload[0] != 0xA1 or payload[1] != 0:
        raise ValueError("not a successful P011 identity response")
    commit = payload[6:18].decode("ascii")
    if len(commit) != 12 or any(c not in "0123456789abcdef" for c in commit.lower()):
        raise ValueError("invalid source commit prefix")
    return {
        "command": payload[0],
        "status": payload[1],
        "schema": payload[2],
        "profile": payload[3],
        "capabilities": payload[4] | (payload[5] << 8),
        "source_commit_prefix": commit,
        "resource_profile_sha256_prefix": payload[18:34].hex(),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Decode a P011 identity-only XNCP response")
    p.add_argument("hex_payload", help="34-byte response as hexadecimal")
    args = p.parse_args()
    try:
        payload = bytes.fromhex(args.hex_payload)
    except ValueError as exc:
        raise SystemExit(f"invalid hex: {exc}") from exc
    print(json.dumps(decode_identity(payload), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
