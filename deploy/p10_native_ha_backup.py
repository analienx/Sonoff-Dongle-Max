"""Narrow, opt-in Home Assistant native FULL-backup helper for Zephyrus.

Only permitted Supervisor commands: backup list, jobs info, native full backup.
No network parameters, credentials, coordinator commands, or restore operations.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

HELPER = Path('C:/Workspace/repos/config/skills/home-assistant-readonly/ha_readonly.py')
Z2M_ADDON = '45df7312_zigbee2mqtt'


def load_connection():
    spec = importlib.util.spec_from_file_location('canonical_ha_readonly', HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError('Canonical host-key-verified HA helper unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.connect('ha')


def query(client, command: str) -> dict:
    allowed = ('ha backups list --raw-json', 'ha jobs info --raw-json')
    if command not in allowed:
        raise ValueError('Unapproved read-only HA query')
    _, out, _ = client.exec_command(command, timeout=25)
    result = json.loads(out.read().decode('utf-8'))
    if out.channel.recv_exit_status() != 0 or result.get('result') != 'ok':
        raise RuntimeError('Native HA query failed')
    return result['data']


def summarize(backup: dict) -> dict:
    content = backup.get('content') or {}
    return {'name': backup.get('name'), 'slug': backup.get('slug'),
            'type': backup.get('type'), 'size_bytes': backup.get('size_bytes'),
            'homeassistant_included': content.get('homeassistant') is True,
            'zigbee2mqtt_addon_included': Z2M_ADDON in content.get('addons', []),
            'native_archive_created': True,
            'coordinator_cross_stack_migration_proven': False}


def perform(client, name: str) -> dict:
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{4,70}', name):
        raise ValueError('Backup name must contain only safe alphanumeric characters, _ or -')
    saved = query(client, 'ha backups list --raw-json')['backups']
    existing = [item for item in saved if item.get('name') == name]
    if existing:
        if len(existing) != 1:
            raise RuntimeError('Duplicate backup names; refuse ambiguity')
        return summarize(existing[0]) | {'already_existed': True}
    active = query(client, 'ha jobs info --raw-json').get('jobs', [])
    if any('backup' in job.get('name', '') and not job.get('done', False) for job in active):
        raise RuntimeError('Home Assistant backup already running')
    # Single fixed mutation: native Supervisor FULL-backup creation; no restore/stop.
    cmd = 'ha backups new --name ' + name + ' --no-progress --raw-json'
    _, out, _ = client.exec_command(cmd, timeout=None)
    out.channel.settimeout(None)
    while not out.channel.exit_status_ready():
        time.sleep(3)
    response = out.read().decode('utf-8', errors='replace')
    if out.channel.recv_exit_status() != 0:
        raise RuntimeError('Supervisor native backup creation failed')
    if response.strip() and json.loads(response).get('result') != 'ok':
        raise RuntimeError('Supervisor reported native backup failure')
    saved = query(client, 'ha backups list --raw-json')['backups']
    matched = [item for item in saved if item.get('name') == name]
    if len(matched) != 1:
        raise RuntimeError('New named backup not found after creation')
    return summarize(matched[0]) | {'already_existed': False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--create', action='store_true',
                        help='Explicitly create a full native HA backup; default only inspects')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{4,70}', args.name):
        parser.error('Invalid backup name')
    client = None
    try:
        client = load_connection()
        if args.create:
            result = perform(client, args.name)
        else:
            entries = query(client, 'ha backups list --raw-json')['backups']
            matches = [item for item in entries if item.get('name') == args.name]
            result = summarize(matches[0]) if len(matches) == 1 else {'found': False}
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if (result.get('zigbee2mqtt_addon_included')
                     and result.get('homeassistant_included') and result.get('type') == 'full') else 3
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print('HA_NATIVE_BACKUP_ERROR: ' + str(exc)[:180], file=sys.stderr)
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == '__main__':
    raise SystemExit(main())
