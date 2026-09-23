"""Offline Zigbee2MQTT backup integrity and cross-stack preflight.

Never reads radio, network or credentials; raw private data stays in local archive.
A Zigbee2MQTT database record is NOT a per-device coordinator security record.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

EXCLUDED = {'.git', 'log', 'logs', '__pycache__'}
REQUIRED = {'database.db', 'configuration.yaml', 'coordinator_backup.json'}
ROLES = {'Coordinator', 'Router', 'EndDevice'}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory(data: bytes) -> dict:
    found, kinds = set(), {key: 0 for key in ROLES}
    for raw in data.splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw)
        role = record.get('type')
        ieee = record.get('ieeeAddr')
        if role not in ROLES or not isinstance(ieee, str) or ieee.lower() in found:
            raise ValueError('Invalid or duplicate Zigbee2MQTT device record')
        found.add(ieee.lower()); kinds[role] += 1
    if kinds['Coordinator'] != 1:
        raise ValueError('Expected exactly one coordinator in database')
    return {'records': len(found), 'roles': kinds}


def preflight(blobs: dict[str, bytes]) -> dict:
    absent = sorted(REQUIRED - blobs.keys())
    if absent:
        return {'status': 'BLOCKED', 'missing_files': absent}
    devices = inventory(blobs['database.db'])
    backup = json.loads(blobs['coordinator_backup.json'])
    entries = backup.get('devices')
    if not isinstance(entries, list):
        raise ValueError('Coordinator backup missing devices array')
    ids = set()
    key_records = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Malformed coordinator backup device record')
        ieee = entry.get('ieee_address')
        if not isinstance(ieee, str) or ieee.lower() in ids:
            raise ValueError('Duplicate or missing coordinator device identifier')
        ids.add(ieee.lower())
        key_records += bool(entry.get('link_key'))
    live = devices['records'] - devices['roles']['Coordinator']
    reasons = []
    stack = backup.get('stack_specific') or {}
    ember = isinstance(stack, dict) and 'ezsp' in stack
    if ember and not entries:
        reasons.append('Ember may omit application-key records by design; verify target trust-center/security state')
    elif len(entries) < live:
        reasons.append('Coordinator device-record coverage is incomplete; assess security requirements')
    if not ember and key_records < len(entries):
        reasons.append('Some backed-up device records lack individual link keys')
    network_fields = ('coordinator_ieee', 'pan_id', 'extended_pan_id', 'channel', 'network_key')
    missing_network_fields = [name for name in network_fields if not backup.get(name)]
    if missing_network_fields:
        reasons.append('Coordinator network identity/security fields missing')
    return {'status': 'PREFLIGHT_REVIEW_REQUIRED' if reasons else 'RECORD_COUNTS_MATCH_ONLY',
            'database': devices, 'coordinator_backup_records': len(entries),
            'coordinator_backup_with_link_key': key_records, 'ember_backup': ember,
            'missing_network_fields': missing_network_fields, 'reasons': reasons,
            'migration_authorized': False}


def collect(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        raise ValueError('Snapshot source directory does not exist')
    result = {}
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root)
        if any(part in EXCLUDED for part in rel.parts) or p.is_dir():
            continue
        if p.is_symlink() or not p.is_file():
            raise ValueError('Snapshot includes unsupported file or symlink')
        if p.stat().st_size > 20_000_000:
            raise ValueError('Unexpected large file in snapshot')
        result[rel.as_posix()] = p.read_bytes()
    if sum(map(len, result.values())) > 100_000_000:
        raise ValueError('Snapshot exceeds safe size bound')
    return result


def archive(root: Path, output: Path) -> dict:
    blobs = collect(root)
    report = preflight(blobs)
    if report.get('missing_files'):
        raise ValueError('Refusing incomplete Zigbee2MQTT folder snapshot')
    if any((parent / '.git').exists() for parent in (output.parent, *output.parents)):
        raise ValueError('Refusing to write secret-bearing archive inside Git tree')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as zipout:
            for name, data in blobs.items():
                zipout.writestr(name, data)
    with zipfile.ZipFile(output) as zin:
        if any(zin.read(name) != data for name, data in blobs.items()):
            raise ValueError('Archive verification failed')
    report['archive_sha256'] = digest(output.read_bytes())
    report['file_hashes'] = {name: digest(data) for name, data in blobs.items()}
    report['archive_file_count'] = len(blobs)
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    snap = sub.add_parser('snapshot', help='Archive an already-local private Z2M data folder')
    snap.add_argument('--source', required=True, type=Path)
    snap.add_argument('--output', required=True, type=Path)
    check = sub.add_parser('inspect', help='Inspect Z2M backup from a local private folder')
    check.add_argument('--source', required=True, type=Path)
    args = p.parse_args(argv)
    try:
        result = (archive(args.source, args.output) if args.action == 'snapshot'
                  else preflight(collect(args.source)))
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if args.action == 'snapshot' else 3
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print('MIGRATION_BACKUP_ERROR: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
