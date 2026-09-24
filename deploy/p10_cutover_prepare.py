"""Capture and inspect a PRIVATE, read-only live Zigbee2MQTT migration snapshot.

Only the canonical pinned HA SSH connection is used. No coordinator/API writes.
This snapshot is a supplement to the full native HA backup, not an atomic backup.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from p10_migration_backup import preflight

HA_HELPER = Path('C:/Workspace/repos/config/skills/home-assistant-readonly/ha_readonly.py')
PRIVATE_ROOT = Path('C:/Workspace/.analienx/sonoff-private').resolve()
REMOTE_ROOTS = ('/config/zigbee2mqtt', '/homeassistant/zigbee2mqtt')
REQUIRED = ('database.db', 'configuration.yaml', 'coordinator_backup.json')
OPTIONAL = ('state.json', 'devices.yaml', 'groups.yaml', 'configuration.yaml.bk')
MAX_FILE_BYTES = 20_000_000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private_target(path: Path) -> Path:
    destination = path.resolve()
    if destination == PRIVATE_ROOT or PRIVATE_ROOT not in destination.parents:
        raise ValueError('Destination must be beneath the private Sonoff workspace')
    if any((p / '.git').exists() for p in (destination, *destination.parents)):
        raise ValueError('Refusing backup inside a Git worktree')
    return destination


def load_ha():
    spec = importlib.util.spec_from_file_location('ha_readonly_p10', HA_HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError('Canonical host-key-verified HA SSH helper unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.connect('ha')


def stable_remote_file(sftp, path: str, required: bool) -> bytes | None:
    try:
        before = sftp.stat(path)
    except OSError:
        if not required:
            return None
        raise RuntimeError('Required Zigbee2MQTT file missing: ' + path.rsplit('/', 1)[-1])
    if not 0 < before.st_size <= MAX_FILE_BYTES:
        raise ValueError('Invalid or excessive live file size: ' + path.rsplit('/', 1)[-1])
    with sftp.open(path, 'rb') as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    after = sftp.stat(path)
    if (len(data) != before.st_size or len(data) > MAX_FILE_BYTES or
            (before.st_size, before.st_mtime) != (after.st_size, after.st_mtime)):
        raise RuntimeError('Zigbee2MQTT file changed during capture: ' + path.rsplit('/', 1)[-1])
    return data


def capture(out: Path) -> dict:
    target = private_target(out)
    if target.exists():
        raise FileExistsError('Refusing to overwrite an earlier migration snapshot')
    client = load_ha()
    try:
        sftp = client.open_sftp()
        root = next((p for p in REMOTE_ROOTS if sftp.exists(p + '/database.db')), None) if hasattr(sftp, 'exists') else None
        if root is None:
            for candidate in REMOTE_ROOTS:
                try:
                    sftp.stat(candidate + '/database.db')
                    root = candidate
                    break
                except OSError:
                    pass
        if root is None:
            raise RuntimeError('Live Zigbee2MQTT data directory was not located')
        blobs = {name: stable_remote_file(sftp, root + '/' + name, True) for name in REQUIRED}
        blobs.update({name: data for name in OPTIONAL
                      if (data := stable_remote_file(sftp, root + '/' + name, False)) is not None})
        report = inspect(blobs)
        target.mkdir(parents=True, exist_ok=False)
        for name, data in blobs.items():
            with (target / name).open('xb') as stream:
                stream.write(data)
        report['snapshot_dir'] = str(target)
        report['captured_files_sha256'] = {name: sha(data) for name, data in blobs.items()}
        report['live_capture_atomic'] = False
        with (target / 'manifest.private.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
        return report
    finally:
        client.close()


def inspect(blobs: dict[str, bytes]) -> dict:
    import yaml
    raw = preflight(blobs)
    conf = yaml.safe_load(blobs['configuration.yaml'])
    backup = json.loads(blobs['coordinator_backup.json'])
    if not isinstance(conf, dict):
        raise ValueError('Invalid Zigbee2MQTT configuration')
    serial = conf.get('serial') or {}
    if not isinstance(serial, dict) or serial.get('adapter') != 'ember':
        raise ValueError('Expected existing production Ember adapter')
    source_port = serial.get('port')
    if not isinstance(source_port, str) or not source_port.startswith('/dev/'):
        raise ValueError('Source coordinator port must be a verified HA USB path')
    if backup.get('channel') not in range(11, 27):
        raise ValueError('Invalid coordinator backup Zigbee channel')
    coordinator = backup.get('coordinator_ieee')
    if not isinstance(coordinator, str) or len(coordinator) != 16:
        raise ValueError('Invalid coordinator IEEE in source backup')
    key = backup.get('network_key')
    if not isinstance(key, dict) or not isinstance(key.get('frame_counter'), int):
        raise ValueError('Network key frame counter missing from source backup')
    return {'status': 'PREPARED_NOT_CUTOVER_APPROVED',
            'captured_utc': datetime.now(timezone.utc).isoformat(),
            'source_adapter': 'ember', 'source_port_sha256': sha(source_port.encode()),
            'source_config_sha256': sha(blobs['configuration.yaml']),
            'coordinator_ieee_sha256': sha(coordinator.encode()),
            'channel': backup['channel'], 'network_frame_counter_present': True,
            'z2m_database': raw['database'],
            'coordinator_device_records': raw['coordinator_backup_records'],
            'ember_empty_device_records_can_be_expected': raw.get('ember_backup') and not backup['devices'],
            'review_reasons': raw['reasons'], 'migration_authorized': False,
            'target_radio2_endpoint_verified_from_ha': False,
            'source_coordinator_ieee_written_to_target': False,
            'source_radio_preservation_required': True,
            'note': 'Read-only live-file snapshot; validate native HA recovery backup separately.'}


def offline(directory: Path) -> dict:
    source = private_target(directory)
    blobs = {name: (source / name).read_bytes() for name in REQUIRED}
    report = inspect(blobs)
    manifest = source / 'manifest.private.json'
    if manifest.exists():
        earlier = json.loads(manifest.read_text(encoding='utf-8'))
        checks = earlier.get('captured_files_sha256') or {}
        report['captured_file_integrity_pass'] = all(
            sha((source / name).read_bytes()) == value for name, value in checks.items())
        if not report['captured_file_integrity_pass']:
            raise RuntimeError('Private migration snapshot changed after capture')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    a = commands.add_parser('capture')
    a.add_argument('--out', required=True, type=Path)
    b = commands.add_parser('inspect')
    b.add_argument('--source', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = capture(args.out) if args.command == 'capture' else offline(args.source)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print('P10_CUTOVER_PREP_ERROR: ' + str(exc)[:160], file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
