"""One-command USB cutover handoff: stop Zigbee2MQTT, cold-backup, stage rollback.

PREPARE is read-only; BEGIN requires explicit --execute and a phase-specific
approval. Never unplugs radios, writes coordinator state, or starts a new mesh.
Only print READY_TO_DISCONNECT_SONOFF after all cold recovery checks succeed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
from p10_cutover_prepare import private_target
from p10_data_bundle import addon_info, load_ha, verify, OPTIONS_NAME
from p10_migration_workflow import stage as stage_source
from p10_outage_freeze import freeze, source_state, PHRASE as FREEZE_APPROVAL

APPROVAL = 'BEGIN_USB_CUTOVER_STOP_AND_BACKUP'


def source_hash(bundle: Path) -> str:
    report = verify(private_target(bundle))
    if report.get('integrity_pass') is not True:
        raise RuntimeError('Existing private source archive failed verification')
    with zipfile.ZipFile(bundle) as archive:
        original = archive.read('data/configuration.yaml')
        addon = json.loads(archive.read(OPTIONS_NAME))['options']
    import yaml
    source = yaml.safe_load(original)['serial']
    if source.get('adapter') != 'ember' or not source.get('port','').startswith('/dev/serial/by-id/'):
        raise RuntimeError('Source archive is not the original Ember USB installation')
    if addon.get('serial', {}).get('port') != source['port'] or addon['serial'].get('adapter') != 'ember':
        raise RuntimeError('Source archive YAML and add-on options disagree')
    return hashlib.sha256(original).hexdigest()


def prepare(bundle: Path, cold_out: Path, stage_out: Path) -> dict:
    expected = source_hash(bundle)
    if private_target(cold_out).exists() or private_target(stage_out).exists():
        raise FileExistsError('Choose NEW private recovery and stage destinations')
    source = source_state(expected)
    if source['state'] != 'started' or source.get('source_yaml_matches') is not True:
        raise RuntimeError('SONOFF production source is not running the expected config')
    return {'status':'DRY_RUN_SOURCE_MATCHES', 'addon_running':True,
            'cold_backup_exists':False,'sonoff_disconnect_authorized':False,
            'next_action':'One-shot approved BEGIN will stop Z2M, cold-backup and stage rollback'}


def begin(bundle: Path, cold_out: Path, stage_out: Path, approval: str) -> dict:
    if approval != APPROVAL:
        raise ValueError('Explicit BEGIN_USB_CUTOVER_STOP_AND_BACKUP approval required')
    # No live changes until destination, original source, and addon status check.
    prepare(bundle, cold_out, stage_out)
    expected = source_hash(bundle)
    freeze(private_target(cold_out), expected, FREEZE_APPROVAL)
    checked = verify(private_target(cold_out))
    if checked.get('integrity_pass') is not True or checked.get('cold_consistent') is not True:
        raise RuntimeError('Final cold backup verification FAILED. Do not disconnect SONOFF.')
    staged = stage_source(private_target(cold_out), private_target(stage_out))
    if staged.get('bundle_cold') is not True or staged.get('bundle_integrity_pass') is not True:
        raise RuntimeError('Cold recovery staging FAILED. Do not disconnect SONOFF.')
    client = load_ha()
    try:
        info = addon_info(client)
        if info.get('state') != 'stopped':
            raise RuntimeError('Zigbee2MQTT restarted during staging. Do not disconnect SONOFF.')
        if info.get('boot') != 'manual' or info.get('watchdog') is True:
            raise RuntimeError('Add-on restart policy changed. Do not disconnect SONOFF.')
    finally:
        client.close()
    return {'status':'READY_TO_DISCONNECT_SONOFF', 'addon_stopped':True,
            'cold_backup_verified':True,'source_rollback_staged':True,
            'cold_bundle_file_count':checked['application_file_count'],
            'physical_sonoff_isolation_performed':False,'target_radio_programmed':False,
            'next_action':'Disconnect SONOFF all power, connect MR4U USB; then use p10_usb_cutover.py'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-bundle', required=True, type=Path)
    parser.add_argument('--cold-out', required=True, type=Path)
    parser.add_argument('--stage-out', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approval', default='')
    args = parser.parse_args(argv)
    try:
        result = (begin(args.source_bundle,args.cold_out,args.stage_out,args.approval)
                  if args.execute else prepare(args.source_bundle,args.cold_out,args.stage_out))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print('P10_USB_HANDOFF_ERROR: ' + str(exc)[:180], file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
