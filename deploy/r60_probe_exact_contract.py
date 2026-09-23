#!/usr/bin/env python3
"""Fixed, non-secret host-side contract consumed by the canonical R60 probe helper."""
from pathlib import Path
import hashlib

EXTENSION_NAME = 'r60_neighbor_extension.cjs'
EXTENSION_SOURCE = Path(__file__).resolve().parents[1] / 'runtime' / EXTENSION_NAME
OWNER_IMAGE = 'ghcr.io/zigbee2mqtt/zigbee2mqtt-aarch64:2.14.0-1'
Z2M_VERSION = '2.14.0'
HERDSMAN_VERSION = '10.9.1'
MAX_LOCAL_GETS = 26


def source_digest():
    return hashlib.sha256(EXTENSION_SOURCE.read_bytes()).hexdigest()


def verify_source():
    source = EXTENSION_SOURCE.read_bytes()
    if not source or len(source) > 16384:
        raise ValueError('diagnostic source missing or unexpectedly large')
    if EXTENSION_NAME != EXTENSION_SOURCE.name:
        raise ValueError('unexpected extension name')
    return source_digest(), source
