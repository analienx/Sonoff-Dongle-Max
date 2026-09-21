#!/usr/bin/env python3
"""Read-only R60 external-extension preflight; NEVER saves, loads or removes an extension.

Run on Zephyrus against the canonical host-key-verified HA read-only helper.
This is observational evidence for a future, separately reviewed deployment broker;
it does not authorize that broker or prove no concurrently starting OTA/map.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex

BASE = Path(__file__).resolve().parents[1]
EXTENSION = BASE / 'runtime' / 'r60_neighbor_extension.cjs'
HELPER = Path(r'C:\Workspace\repos\config\skills\home-assistant-readonly\ha_readonly.py')

REMOTE = r'''import datetime, json, pathlib, subprocess, yaml
root = next((p for p in (pathlib.Path('/config/zigbee2mqtt'), pathlib.Path('/homeassistant/zigbee2mqtt')) if (p/'configuration.yaml').exists()), None)
if root is None: raise RuntimeError('Z2M data root not located')
config = yaml.safe_load((root/'configuration.yaml').read_text()) or {}
ps = subprocess.run(['docker', 'ps', '--format', '{{json .}}'], capture_output=True, text=True, timeout=8, check=True)
containers = [json.loads(line) for line in ps.stdout.splitlines() if line.strip()]
owners = [x for x in containers if 'zigbee2mqtt' in (x.get('Names', '')+' '+x.get('Image', '')).lower()]
result = {'captured_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'owner_count': len(owners), 'serial_adapter': (config.get('serial') or {}).get('adapter'),
          'extension_file_preexisting': (root/'external_extensions'/'r60_neighbor_extension.cjs').exists(),
          'bridge_base_topic': (config.get('mqtt') or {}).get('base_topic', 'zigbee2mqtt'),
          'owner_image': None, 'owner_started_utc': None,
          'owner_running': None, 'z2m_package_version': None, 'herdsman_version': None,
          'external_extension_loader_present': False}
if len(owners) == 1:
 owner = owners[0]; container = owner['ID']; result['owner_image'] = owner['Image']
 state = subprocess.run(['docker','inspect','--format','{{json .State}}',container],capture_output=True,text=True,timeout=8,check=True)
 status=json.loads(state.stdout); result['owner_started_utc']=status.get('StartedAt'); result['owner_running']=status.get('Running')
 js = """const fs=require('node:fs');function ver(a){for(const p of a){try{return JSON.parse(fs.readFileSync(p,'utf8')).version}catch{}}return null}const roots=['/app','/usr/src/app'];const loader=roots.some(p=>fs.existsSync(p+'/dist/extension/externalExtensions.js')||fs.existsSync(p+'/lib/extension/externalExtensions.js'));console.log(JSON.stringify({z2m:ver(roots.map(p=>p+'/package.json')),herdsman:ver(roots.map(p=>p+'/node_modules/zigbee-herdsman/package.json')),loader}));"""
 p = subprocess.run(['docker','exec',container,'node','-e',js],capture_output=True,text=True,timeout=8,check=True)
 versions=json.loads(p.stdout); result['z2m_package_version']=versions.get('z2m'); result['herdsman_version']=versions.get('herdsman'); result['external_extension_loader_present']=bool(versions.get('loader'))
print(json.dumps(result,sort_keys=True))
'''


def evaluate(record: dict, extension_hash: str) -> dict:
    """Fail-closed static preflight, NOT a production-authorization decision."""
    problems = []
    if record.get('owner_count') != 1: problems.append('owner_count_mismatch')
    if record.get('owner_running') is not True: problems.append('owner_not_running')
    if record.get('serial_adapter') != 'ember': problems.append('wrong_adapter')
    if record.get('z2m_package_version') != '2.14.0': problems.append('z2m_version_mismatch')
    if record.get('herdsman_version') != '10.9.1': problems.append('herdsman_version_mismatch')
    if record.get('external_extension_loader_present') is not True: problems.append('loader_unverified')
    if record.get('extension_file_preexisting') is not False: problems.append('existing_extension_conflict')
    if not isinstance(record.get('owner_started_utc'), str) or not record['owner_started_utc'].startswith('20'): problems.append('owner_epoch_missing')
    if not isinstance(extension_hash, str) or len(extension_hash) != 64 or any(c not in '0123456789abcdef' for c in extension_hash): problems.append('extension_hash_invalid')
    return {'captured_utc': record.get('captured_utc'), 'owner_started_utc': record.get('owner_started_utc'),
            'owner_image': record.get('owner_image'), 'owner_count': record.get('owner_count'),
            'z2m_package_version': record.get('z2m_package_version'), 'herdsman_version': record.get('herdsman_version'),
            'external_extension_loader_present': record.get('external_extension_loader_present'),
            'extension_file_preexisting': record.get('extension_file_preexisting'), 'extension_sha256': extension_hash,
            'static_preflight_ok': not problems, 'blockers': problems,
            'deployment_authorized': False,
            'not_proven': ['current in-memory API shape', 'no concurrent OTA/pairing/map',
                           'approved deterministic mutation broker and rollback', 'stable owner epoch during operation']}


def main() -> None:
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--alias', default='ha')
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('ha_readonly', HELPER)
    if spec is None or spec.loader is None: raise RuntimeError('canonical helper unavailable')
    helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    client=helper.connect(args.alias)
    try:
        _,out,err=client.exec_command('python3 -c '+shlex.quote(REMOTE),timeout=30)
        payload=out.read().decode('utf-8','replace')
        stderr=err.read().decode('utf-8','replace')
        if out.channel.recv_exit_status(): raise RuntimeError('read-only owner inspection failed: '+stderr[:180])
        observed=json.loads(payload)
    finally:
        client.close()
    result=evaluate(observed,hashlib.sha256(EXTENSION.read_bytes()).hexdigest())
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__ == '__main__': main()
