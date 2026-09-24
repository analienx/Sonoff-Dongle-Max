"""Narrow, opt-in live Zigbee2MQTT YAML + add-on-options apply/rollback.

Default is a read-only plan. The privileged apply path requires a previously
verified COLD bundle, byte-identical expected running config, stopped add-on,
explicit isolation attestations, and an exact approval phrase. This does NOT
write radio IEEE/NVRAM, isolate radios, start Z2M or certify a migration.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import sys

from p10_cutover_prepare import private_target, REMOTE_ROOTS
from p10_data_bundle import addon_info, load_ha
from p10_ha_state import addon_quiescent

ADDON = '45df7312_zigbee2mqtt'
PHRASES = {'target': 'APPLY_MR4U_ONLY_AFTER_SONOFF_ISOLATION',
           'rollback': 'ROLLBACK_ONLY_AFTER_MR4U_ZIGBEE_ISOLATION'}

# Executed on the authorized HA host only after local safety checks. Payload
# enters over SSH stdin: no credentials, network keys or YAML in argv or logs.
REMOTE_APPLY = r'''
import base64, hashlib, json, os, pathlib, stat, sys, urllib.request, uuid, subprocess
p=json.load(sys.stdin)
slug='45df7312_zigbee2mqtt'
root=pathlib.Path(p['root'])
if str(root) not in ('/config/zigbee2mqtt','/homeassistant/zigbee2mqtt'):
 raise RuntimeError('Unexpected Zigbee2MQTT data root')
cfg=root/'configuration.yaml'
if not root.is_dir() or cfg.is_symlink() or not cfg.is_file():
 raise RuntimeError('Unexpected live configuration file')
sha=lambda b: hashlib.sha256(b).hexdigest()
old_bytes=cfg.read_bytes()
if sha(old_bytes)!=p['expected_yaml_sha256']:
 raise RuntimeError('Live YAML changed since staging; no write performed')
new_bytes=base64.b64decode(p['new_yaml_b64'],validate=True)
if sha(new_bytes)!=p['new_yaml_sha256']:
 raise RuntimeError('Proposed YAML checksum mismatch')
header={'Authorization':'Bearer '+os.environ['SUPERVISOR_TOKEN'],
        'Content-Type':'application/json'}
url='http://supervisor/addons/'+slug

def request(method, suffix, data=None):
 raw=None if data is None else json.dumps(data,sort_keys=True).encode()
 req=urllib.request.Request(url+suffix, data=raw,headers=header,method=method)
 with urllib.request.urlopen(req,timeout=30) as response:
  body=json.loads(response.read().decode())
 if body.get('result')!='ok':
  raise RuntimeError('Supervisor rejected add-on options operation')
 return body.get('data')

def quiescent():
 info=request('GET','/info')
 if info.get('state') not in ('stopped','error'):
  raise RuntimeError('Zigbee2MQTT Supervisor state is not quiescent')
 check=subprocess.run(['docker','inspect','--format','{{.State.Running}}','app_'+slug],capture_output=True,text=True,timeout=15)
 if check.returncode!=0 or check.stdout.strip()!='false':
  raise RuntimeError('Zigbee2MQTT container must be verified not running')
 return info
info=quiescent()
if info.get('options')!=p['expected_options']:
 raise RuntimeError('Live add-on options changed since staging')
# Two-layer update: write candidate first, configure Supervisor second, and
# atomically replace YAML last. On failure before replace restore old options.
tmp=root/('.p10-migration-'+uuid.uuid4().hex+'.tmp')
fd=os.open(str(tmp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
original_metadata=os.stat(str(cfg))
os.fchmod(fd,stat.S_IMODE(original_metadata.st_mode))
if os.geteuid()==0:
 os.fchown(fd,original_metadata.st_uid,original_metadata.st_gid)
updated_options=False
try:
 with os.fdopen(fd,'wb') as file:
  file.write(new_bytes); file.flush(); os.fsync(file.fileno())
 if sha(tmp.read_bytes())!=p['new_yaml_sha256']:
  raise RuntimeError('Staged remote YAML did not match proposed checksum')
 request('POST','/options',{'options':p['new_options']})
 updated_options=True
 if cfg.read_bytes()!=old_bytes or quiescent().get('state') not in ('stopped','error'):
  raise RuntimeError('Source changed while staging; returning old options')
 os.replace(str(tmp),str(cfg))
 updated_options=False
finally:
 if tmp.exists(): tmp.unlink()
 if updated_options:
  request('POST','/options',{'options':p['expected_options']})
current=quiescent()
if current.get('options')!=p['new_options'] or sha(cfg.read_bytes())!=p['new_yaml_sha256']:
 raise RuntimeError('Post-apply mismatch; keep Zigbee2MQTT stopped')
print(json.dumps({'two_layer_config_applied':True,'addon_remains_stopped':True,
                  'yaml_sha256':p['new_yaml_sha256'],'radio_touched':False}))
'''


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stage_files(directory: Path, phase: str) -> dict:
    source = private_target(directory)
    state = json.loads((source / 'cutover_state.private.json').read_text(encoding='utf-8'))
    if state.get('bundle_cold') is not True or state.get('bundle_integrity_pass') is not True:
        raise RuntimeError('A verified FINAL cold Zigbee2MQTT bundle is required')
    if state.get('target_znp_verified_from_ha') is not True:
        raise RuntimeError('No exact target P10 endpoint is staged and verified')
    if phase not in PHRASES:
        raise ValueError('Unrecognized migration phase')
    files = {name: (source / name).read_bytes() for name in
             ('rollback_configuration.yaml','target_configuration.yaml',
              'rollback_addon_options.private.json','target_addon_options.private.json')}
    for name, data in files.items():
        recorded = state.get('rollback_and_target_hashes',{}).get(name)
        if recorded != digest(data):
            raise RuntimeError('Staged file integrity mismatch: ' + name)
    old, new = ('rollback','target') if phase == 'target' else ('target','rollback')
    old_wrapper = json.loads(files[old+'_addon_options.private.json'])
    new_wrapper = json.loads(files[new+'_addon_options.private.json'])
    if old_wrapper.get('addon_slug')!=ADDON or new_wrapper.get('addon_slug')!=ADDON:
        raise RuntimeError('Wrong Home Assistant add-on options record')
    return {'expected_yaml': files[old+'_configuration.yaml'],
            'new_yaml': files[new+'_configuration.yaml'],
            'expected_options': old_wrapper['options'],
            'new_options': new_wrapper['options']}


def live_plan(directory: Path, phase: str) -> dict:
    material = stage_files(directory, phase)
    client = load_ha()
    try:
        info = addon_info(client)
        quiet = addon_quiescent(client, info)
        sftp = client.open_sftp()
        roots, inconsistent = [], False
        for root in REMOTE_ROOTS:
            try:
                with sftp.open(root+'/configuration.yaml','rb') as file:
                    if digest(file.read(2*1024*1024)) == digest(material['expected_yaml']):
                        roots.append(root)
                    else:
                        inconsistent = True
            except FileNotFoundError:
                continue
        unique_match = bool(roots) and not inconsistent
        return {'phase': phase,'addon_state':info['state'],
                'expected_yaml_present':unique_match,
                'addon_options_match_expected':info['options']==material['expected_options'],
                'data_root':roots[0] if unique_match else None,
                'addon_container_running': quiet['addon_container_running'],
                'safe_to_apply_config': quiet['addon_quiescent'] and unique_match and
                       info['options']==material['expected_options'],
                'radio_isolation_verified_by_software':False, 'live_change_performed':False}
    finally:
        client.close()


def apply(directory: Path, phase: str, approval: str, acknowledgements: list[str]) -> dict:
    if approval != PHRASES[phase]:
        raise ValueError('Exact approval phrase required for live configuration change')
    required = ({'source-isolated','source-backup-preserved','effective-ieee-verified','exclusive-radio-client'}
                if phase=='target' else {'target-isolated'})
    if not required <= set(acknowledgements):
        raise ValueError('Required operator radio/network attestations missing')
    plan = live_plan(directory,phase)
    if not plan['safe_to_apply_config']:
        raise RuntimeError('Live configuration or add-on state differs from prepared plan')
    material = stage_files(directory,phase)
    payload = {'root':plan['data_root'],
               'expected_yaml_sha256':digest(material['expected_yaml']),
               'new_yaml_sha256':digest(material['new_yaml']),
               'new_yaml_b64':base64.b64encode(material['new_yaml']).decode('ascii'),
               'expected_options':material['expected_options'],
               'new_options':material['new_options']}
    client = load_ha()
    try:
        command='python3 -c '+shlex.quote(REMOTE_APPLY)
        stdin, stdout, stderr = client.exec_command(command,timeout=None)
        stdin.channel.settimeout(None); stdout.channel.settimeout(None)
        stdin.write(json.dumps(payload,sort_keys=True)); stdin.channel.shutdown_write()
        raw = stdout.read().decode('utf-8',errors='replace')
        status = stdout.channel.recv_exit_status()
        if status != 0:
            # Intentionally DO NOT echo remote stderr; it could include private data.
            raise RuntimeError('HA narrow config operation failed; leave add-on stopped and inspect privately')
        response = json.loads(raw)
        if response.get('two_layer_config_applied') is not True:
            raise RuntimeError('HA did not confirm two-layer configuration update')
    finally:
        client.close()
    # Read-only post-check; the add-on remains stopped throughout this command.
    checked = live_plan(directory,'rollback' if phase=='target' else 'target')
    if not checked['safe_to_apply_config']:
        raise RuntimeError('Post-apply status mismatch; leave add-on stopped')
    return {'phase':phase,'two_layer_config_applied':True,
            'addon_remains_stopped':True,'radio_changed':False,
            'next_step':'Explicitly verify radio isolation/identity, then start Z2M separately'}


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',required=True,type=Path)
    p.add_argument('--phase',required=True,choices=tuple(PHRASES))
    p.add_argument('--execute',action='store_true')
    p.add_argument('--approval',default='')
    p.add_argument('--ack',action='append',default=[],choices=('source-isolated','target-isolated',
                       'source-backup-preserved','effective-ieee-verified','exclusive-radio-client'))
    a=p.parse_args(argv)
    try:
        result=apply(a.stage,a.phase,a.approval,a.ack) if a.execute else live_plan(a.stage,a.phase)
        print(json.dumps(result,indent=2,sort_keys=True))
        return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,json.JSONDecodeError) as e:
        print('P10_HA_APPLY_ERROR: '+str(e)[:170],file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
