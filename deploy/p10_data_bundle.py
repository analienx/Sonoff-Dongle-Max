"""Private, integrity-checked Zigbee2MQTT migration bundle.

No service/radio/configuration writes. 'cold' refuses to run unless the Z2M app is
already stopped; 'hot' is a provisional, non-atomic capture for rehearsal only.
Capture all application data except regenerated log/ and logs/ folders, plus
Home Assistant add-on options that can override configuration.yaml.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

from p10_cutover_prepare import load_ha, private_target, REMOTE_ROOTS
from p10_migration_backup import preflight

ADDON = '45df7312_zigbee2mqtt'
REQUIRED = frozenset({'database.db', 'configuration.yaml', 'coordinator_backup.json'})
SKIP_TOPLEVEL = frozenset({'log', 'logs'})  # non-restorable operational logs only
MAX_FILES = 10000
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
CHUNK = 1024 * 1024
MANIFEST_NAME = 'meta/manifest.private.json'
OPTIONS_NAME = 'meta/addon_options.private.json'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def addon_info(client) -> dict:
    _, output, _ = client.exec_command('ha apps info ' + ADDON + ' --raw-json', timeout=30)
    data = json.loads(output.read().decode('utf-8'))
    if output.channel.recv_exit_status() != 0 or data.get('result') != 'ok':
        raise RuntimeError('Unable to verify Zigbee2MQTT add-on status')
    info = data.get('data')
    if not isinstance(info, dict) or info.get('slug') != ADDON:
        raise RuntimeError('Unexpected Zigbee2MQTT add-on identity')
    if not isinstance(info.get('options'), dict):
        raise RuntimeError('Add-on options unavailable: do not assume YAML is complete')
    return info


def find_data_root(sftp) -> str:
    for root in REMOTE_ROOTS:
        try:
            mode = sftp.lstat(root).st_mode
            for name in REQUIRED:
                item = sftp.lstat(root + '/' + name)
                if not stat.S_ISREG(item.st_mode):
                    raise RuntimeError('Required application file is not regular: ' + name)
            if stat.S_ISDIR(mode):
                return root
        except FileNotFoundError:
            continue
    raise RuntimeError('Unable to identify complete Zigbee2MQTT data folder')


def walk(sftp, root: str) -> list[tuple[str, str, object]]:
    files: list[tuple[str, str, object]] = []
    queue = [('', root)]
    total = 0
    while queue:
        prefix, absolute = queue.pop()
        for entry in sftp.listdir_attr(absolute):
            name = entry.filename
            if name in ('.', '..') or '/' in name or '\\' in name or '\x00' in name:
                raise ValueError('Unexpected SFTP entry name')
            rel = prefix + name
            mode = entry.st_mode
            if stat.S_ISLNK(mode):
                raise ValueError('Refusing symlink in application data: ' + rel)
            if not prefix and name in SKIP_TOPLEVEL:
                if not stat.S_ISDIR(mode):
                    raise ValueError('Log exclusion unexpectedly refers to a file')
                continue
            if stat.S_ISDIR(mode):
                queue.append((rel + '/', absolute + '/' + name))
                continue
            if not stat.S_ISREG(mode):
                raise ValueError('Refusing non-regular entry in application data: ' + rel)
            if entry.st_size < 0 or entry.st_size > MAX_FILE_BYTES:
                raise ValueError('Unexpectedly large application file: ' + rel)
            files.append((rel, absolute + '/' + name, entry))
            total += entry.st_size
            if len(files) > MAX_FILES or total > MAX_TOTAL_BYTES:
                raise ValueError('Application data exceeds bounded capture limits')
    if not REQUIRED <= {rel for rel, _, _ in files}:
        raise RuntimeError('Missing Zigbee2MQTT recovery file')
    return sorted(files, key=lambda row: row[0])


def _read_to_archive(sftp, absolute: str, original, zipout, arcname: str) -> dict:
    before = sftp.lstat(absolute)
    if not stat.S_ISREG(before.st_mode) or (before.st_size, before.st_mtime) != (original.st_size, original.st_mtime):
        raise RuntimeError('File changed before capture: ' + arcname)
    digest = hashlib.sha256()
    read = 0
    with sftp.open(absolute, 'rb') as source, zipout.open(arcname, 'w') as target:
        while chunk := source.read(CHUNK):
            read += len(chunk)
            if read > MAX_FILE_BYTES or read > original.st_size:
                raise RuntimeError('File changed during capture: ' + arcname)
            digest.update(chunk)
            target.write(chunk)
    after = sftp.lstat(absolute)
    if read != original.st_size or (after.st_size, after.st_mtime) != (original.st_size, original.st_mtime):
        raise RuntimeError('File changed during capture: ' + arcname)
    return {'bytes': read, 'sha256': digest.hexdigest()}


def _safe_names(archive) -> None:
    seen = set()
    for name in archive.namelist():
        parts = PurePosixPath(name).parts
        if (not parts or name.startswith('/') or '\\' in name or '..' in parts
                or name in seen or parts[0] not in ('data', 'meta')):
            raise ValueError('Unexpected archive member path or duplicate')
        seen.add(name)


def verify(path: Path) -> dict:
    path = private_target(path)
    with zipfile.ZipFile(path) as archive:
        _safe_names(archive)
        manifest = json.loads(archive.read(MANIFEST_NAME))
        files = manifest['files']
        if not isinstance(files, dict) or not REQUIRED <= {n.removeprefix('data/') for n in files}:
            raise ValueError('Bundle does not include required recovery files')
        if set(archive.namelist()) != set(files) | {MANIFEST_NAME}:
            raise ValueError('Archive inventory differs from manifest')
        for name, recorded in files.items():
            digest, size = hashlib.sha256(), 0
            with archive.open(name) as stream:
                while chunk := stream.read(CHUNK):
                    digest.update(chunk); size += len(chunk)
            if digest.hexdigest() != recorded['sha256'] or size != recorded['bytes']:
                raise ValueError('Archive integrity check failed: ' + name)
        options = json.loads(archive.read(OPTIONS_NAME))
        if not isinstance(options.get('options'), dict):
            raise ValueError('Add-on options are missing or malformed')
        blobs = {n: archive.read('data/' + n) for n in REQUIRED}
        preflight(blobs)  # Reject malformed device database/backup, without requiring cross-stack success.
        return {'integrity_pass': True, 'mode': manifest['mode'],
                'cold_consistent': manifest['mode'] == 'cold',
                'application_file_count': len(files) - 1,
                'total_application_bytes': sum(v['bytes'] for n, v in files.items() if n.startswith('data/')),
                'addon_options_included': True, 'excluded_top_level_log_folders': sorted(SKIP_TOPLEVEL),
                'network_migration_performed': False}


def capture(out: Path, mode: str) -> dict:
    out = private_target(out)
    if out.suffix.lower() != '.zip' or out.exists():
        raise ValueError('A new private .zip path is required; overwriting is forbidden')
    client = load_ha()
    try:
        info = addon_info(client)
        if mode == 'cold' and info.get('state') != 'stopped':
            raise RuntimeError('Cold capture requires the Zigbee2MQTT add-on to be stopped first')
        sftp = client.open_sftp()
        root = find_data_root(sftp)
        files = walk(sftp, root)
        out.parent.mkdir(parents=True, exist_ok=True)
        records = {}
        options = json.dumps({'addon_slug': ADDON, 'options': info['options'],
                              'version': info.get('version'), 'boot': info.get('boot'),
                              'watchdog': info.get('watchdog')}, sort_keys=True).encode()
        with out.open('xb') as target, zipfile.ZipFile(target, mode='w', compression=zipfile.ZIP_DEFLATED,
                                                       compresslevel=3, allowZip64=True) as archive:
            for relative, remote_path, entry in files:
                name = 'data/' + relative
                records[name] = _read_to_archive(sftp, remote_path, entry, archive, name)
            archive.writestr(OPTIONS_NAME, options)
            records[OPTIONS_NAME] = {'bytes': len(options), 'sha256': sha(options)}
            if mode == 'cold' and addon_info(client).get('state') != 'stopped':
                raise RuntimeError('Add-on restarted during cold capture: reject this bundle')
            manifest = {'format': 'p10-z2m-data-bundle-v1', 'mode': mode,
                        'captured_utc': datetime.now(timezone.utc).isoformat(),
                        'source_addon_state': info['state'], 'files': records,
                        'excluded_top_level_log_folders': sorted(SKIP_TOPLEVEL),
                        'addon_environment_overrides_independently_verified': False,
                        'atomic_capture_guaranteed': mode == 'cold'}
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, sort_keys=True))
        checked = verify(out)
        return checked | {'private_bundle_created': True, 'private_bundle_path': str(out)}
    finally:
        client.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    a = sub.add_parser('capture'); a.add_argument('--out', required=True, type=Path)
    a.add_argument('--mode', required=True, choices=['hot', 'cold'])
    b = sub.add_parser('verify'); b.add_argument('--bundle', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = capture(args.out, args.mode) if args.action == 'capture' else verify(args.bundle)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print('P10_DATA_BUNDLE_ERROR: ' + str(exc)[:180], file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
