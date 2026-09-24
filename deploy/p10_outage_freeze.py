"""One-shot operator-authorized Zigbee2MQTT stop + complete private cold capture.

This helper is inert without --execute and an exact operator approval phrase.
It does not isolate or change either radio, apply configs, start Z2M or migrate a
network. It is a narrow HA service operation, not an arbitrary remote shell.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

from p10_cutover_prepare import REMOTE_ROOTS, private_target
from p10_data_bundle import ADDON, addon_info, capture, load_ha

PHRASE = 'STOP_Z2M_FOR_MR4U_MIGRATION'


def source_state(expected_sha256: str) -> dict:
    if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('Expected original YAML SHA-256 must be 64 lowercase hex characters')
    client = load_ha()
    try:
        info = addon_info(client)
        sftp = client.open_sftp()
        available = []
        for root in REMOTE_ROOTS:
            try:
                with sftp.open(root + '/configuration.yaml', 'rb') as stream:
                    content = stream.read(2 * 1024 * 1024)
                available.append((root, hashlib.sha256(content).hexdigest()))
            except FileNotFoundError:
                continue
        valid = [root for root, digest in available if digest == expected_sha256]
        if len(valid) != 1:
            raise RuntimeError('Live source YAML does not match the private cutover snapshot')
        return {'state': info['state'], 'source_yaml_matches': True,
                'addon_boot_mode': info.get('boot'), 'addon_watchdog_configured': info.get('watchdog'),
                'coordinator_radio_isolated': False, 'source_data_root': valid[0]}
    finally:
        client.close()


def freeze(out: Path, expected_sha256: str, approval: str) -> dict:
    path = private_target(out)
    if approval != PHRASE:
        raise ValueError('Operator approval phrase does not match; no live actions performed')
    if path.exists():
        raise FileExistsError('Cold recovery archive already exists')
    previous = source_state(expected_sha256)
    if previous['state'] != 'started':
        raise RuntimeError('Expected running production Zigbee2MQTT add-on before outage')
    client = load_ha()
    try:
        info = addon_info(client)
        if info['state'] != 'started':
            raise RuntimeError('Source Zigbee2MQTT state changed; refusing stop')
        command = 'ha apps stop ' + ADDON + ' --no-progress --raw-json'
        _, response, _ = client.exec_command(command, timeout=None)
        response.channel.settimeout(None)
        response.channel.recv_exit_status()
        if addon_info(client).get('state') != 'stopped':
            raise RuntimeError('Zigbee2MQTT did not remain stopped; do not isolate SONOFF')
    finally:
        client.close()
    # Radio is deliberately NOT isolated. This capture must finish first.
    result = capture(path, 'cold')
    if not result.get('cold_consistent'):
        raise RuntimeError('Cold bundle was not verified; leave SONOFF connected for recovery')
    return {'status': 'SOURCE_ADDON_STOPPED_COLD_BUNDLE_VERIFIED',
            'source_yaml_matches': True, 'cold_bundle_file_count': result['application_file_count'],
            'symlink_dependencies_present': result['symlink_dependencies_present'],
            'private_bundle_path': str(path), 'sonoff_physically_isolated': False,
            'target_coordinator_activated': False, 'next_step_requires_operator_physical_isolation': True}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--expected-source-config-sha256', required=True)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--approval', default='')
    args = p.parse_args(argv)
    try:
        if args.execute:
            result = freeze(args.out, args.expected_source_config_sha256, args.approval)
        else:
            result = source_state(args.expected_source_config_sha256) | {
                'status': 'DRY_RUN_ONLY', 'live_change_performed': False,
                'approval_required': PHRASE, 'cold_bundle_will_be_created': str(private_target(args.out))}
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print('P10_OUTAGE_FREEZE_ERROR: ' + str(exc)[:150], file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
