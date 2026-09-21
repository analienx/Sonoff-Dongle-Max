#!/usr/bin/env python3
"""Bounded read-only #19 baseline via the canonical SSH/host-key helper; no Zigbee commands."""
import argparse
import importlib.util
import json
from pathlib import Path
import shlex
import sys

HELPER = Path(r'C:\Workspace\repos\config\skills\home-assistant-readonly\ha_readonly.py')
spec = importlib.util.spec_from_file_location('ha_readonly', HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

REMOTE = r'''import collections, datetime, json, os, pathlib, re, subprocess, yaml
now=datetime.datetime.now(datetime.timezone.utc)
root=next((p for p in (pathlib.Path('/config/zigbee2mqtt'),pathlib.Path('/homeassistant/zigbee2mqtt')) if (p/'configuration.yaml').exists()),None)
if root is None: raise RuntimeError('Z2M path not found')
cfg=yaml.safe_load((root/'configuration.yaml').read_text()) or {}
adv=cfg.get('advanced') or {}
devices=[]
for line in (root/'database.db').open(errors='replace'):
 try: d=json.loads(line)
 except ValueError: continue
 if d.get('type') in ('Router','EndDevice','Coordinator'): devices.append(d)
result={'captured_utc':now.isoformat(),'database_mtime_utc':datetime.datetime.fromtimestamp((root/'database.db').stat().st_mtime,datetime.timezone.utc).isoformat(),'roles':dict(collections.Counter(d.get('type') for d in devices)),'configured_channel':adv.get('channel'),'configured_tx':adv.get('transmit_power'),'adapter':(cfg.get('serial') or {}).get('adapter'),'log_directories':[],'docker':None}
try:
 p=subprocess.run(['docker','ps','--format','{{.ID}} {{.Names}} {{.Image}}'],capture_output=True,text=True,timeout=5)
 if p.returncode==0:
  matching=[x for x in p.stdout.splitlines() if 'zigbee' in x.lower()]
  result['docker']={'owner_candidates':matching,'count':len(matching)}
except (FileNotFoundError,subprocess.TimeoutExpired): pass
logroot=root/'log'
if logroot.exists():
 dirs=sorted((p for p in logroot.iterdir() if p.is_dir()),key=lambda p:p.stat().st_mtime,reverse=True)[:2]
 rx=re.compile(r'ROUTE_ERROR_([A-Z_]+) for "(\d+)"')
 for directory in dirs:
  counts=collections.Counter(); examples=[]; start=None; end=None; n=0
  for f in directory.glob('*.log'):
   if f.stat().st_size>30_000_000:continue
   for line in f.open(errors='replace'):
    stamp=re.match(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]',line)
    if stamp:
     start=stamp.group(1) if start is None else min(start,stamp.group(1))
     end=stamp.group(1) if end is None else max(end,stamp.group(1))
    match=rx.search(line)
    if match:counts['ROUTE_ERROR_'+match.group(1)]+=1
    if 'ADDRESS_CONFLICT' in line or 'ID conflict' in line:counts['address_conflict_lines']+=1
    if 'SLStatus.BUSY' in line:counts['busy_lines']+=1
    if 'Failed to' in line and ('publish' not in line):counts['failed_to_lines']+=1
    if 'ASH' in line and ('ERROR' in line or 'error' in line):counts['ash_error_lines']+=1
    n+=1
  result['log_directories'].append({'name':directory.name,'first_log_time':start,'last_log_time':end,'lines':n,'counts':dict(counts)})
# Extra bounded session and failure taxonomy (no raw log lines exported).
if result['docker'] and result['docker']['owner_candidates']:
 container=result['docker']['owner_candidates'][0].split()[0]
 p=subprocess.run(['docker','inspect','--format','{{.State.StartedAt}} {{.RestartCount}}',container],capture_output=True,text=True,timeout=6)
 if p.returncode==0:result['docker']['started_utc_restart_count']=p.stdout.strip()
for entry in result['log_directories']:
 directory=logroot/entry['name']; patterns=collections.Counter();by_minute=collections.Counter();map_class=collections.Counter();failure_class=collections.Counter();route_targets=collections.Counter()
 for f in directory.glob('*.log'):
  if f.stat().st_size>30_000_000:continue
  for line in f.open(errors='replace'):
   match=rx.search(line)
   if match:
    by_minute[line[1:17]]+=1
    route_targets[(match.group(1),match.group(2))]+=1
   low=line.lower()
   if 'network map' in low or 'networkmap' in low or 'mgmt_lqi' in low or 'mgmt_rtg' in low or 'neighbor table' in low or 'routing table' in low:map_class['mentions']+=1
   if 'lqi failed' in low or 'failed to execute lqi' in low:map_class['lqi_failure']+=1
   if 'routing table failed' in low or 'failed to execute routing' in low:map_class['routing_failure']+=1
   if 'failed to' in low:
    if 'read' in low:failure_class['read']+=1
    if 'write' in low:failure_class['write']+=1
    if 'command' in low:failure_class['command']+=1
    if 'ping' in low:failure_class['ping']+=1
    if 'lqi' in low:failure_class['lqi']+=1
   if 'network down' in low:patterns['network_down']+=1
   if 'reset' in low and ('ember' in low or 'ezsp' in low or 'ash' in low):patterns['ncp_reset_mention']+=1
 entry.update({'map':dict(map_class),'failed_to_subclasses':dict(failure_class),'signal_mentions':dict(patterns),'route_error_peak_minute':max(by_minute.values(),default=0),'route_target_distinct':len(route_targets)})
if result['docker'] and result['docker']['owner_candidates']:
 js="for(const p of ['/app/node_modules/zigbee-herdsman/package.json','/usr/src/app/node_modules/zigbee-herdsman/package.json','/app/dist/node_modules/zigbee-herdsman/package.json']){try{console.log(require(p).version);break}catch(e){}}"
 p=subprocess.run(['docker','exec',container,'node','-e',js],capture_output=True,text=True,timeout=8)
 if p.returncode==0 and re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}',p.stdout.strip()):result['herdsman_version']=p.stdout.strip()
for entry in result['log_directories'][:1]:
 versions=collections.Counter()
 for f in (logroot/entry['name']).glob('*.log'):
  if f.stat().st_size>30_000_000:continue
  for i,line in enumerate(f.open(errors='replace')):
   if i>450:break
   if 'EmberZNet' in line:
    match=re.search(r'EmberZNet[^\d]{0,30}(\d+\.\d+\.\d+)',line)
    if match:versions['ember_stack_'+match.group(1)]+=1
   if 'EZSP' in line:
    match=re.search(r'EZSP[^\d]{0,20}(\d{1,2})\b',line)
    if match:versions['ezsp_'+match.group(1)]+=1
   if 'channel' in line.lower():
    match=re.search(r'channel[^\d]{0,12}(\d{1,2})\b',line,re.I)
    if match:versions['log_channel_'+match.group(1)]+=1
 entry['startup_version_mentions']=dict(versions)
print(json.dumps(result,sort_keys=True))
'''
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--alias', default='ha')
    args = parser.parse_args()
    client = helper.connect(args.alias)
    try:
        command = 'python3 -c ' + shlex.quote(REMOTE)
        _, stdout, stderr = client.exec_command(command, timeout=30)
        payload = stdout.read().decode('utf-8', 'replace')
        error = stderr.read().decode('utf-8', 'replace')
        if stdout.channel.recv_exit_status():
            raise RuntimeError('HA read-only query failed: ' + error[:300])
        print(json.dumps(json.loads(payload), indent=2))
    finally:
        client.close()

if __name__ == '__main__':
    main()
