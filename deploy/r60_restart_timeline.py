#!/usr/bin/env python3
"""Read-only restart timeline: structured event counts only, never print Zigbee IDs or raw logs."""
import importlib.util
import json
from pathlib import Path
import shlex

HELPER = Path(r'C:\Workspace\repos\config\skills\home-assistant-readonly\ha_readonly.py')
REMOTE = r'''import collections, datetime, json, pathlib, re, subprocess
root=next((p for p in (pathlib.Path('/config/zigbee2mqtt'),pathlib.Path('/homeassistant/zigbee2mqtt')) if (p/'log').exists()),None)
if root is None: raise RuntimeError('Z2M log root missing')
folders=sorted((p for p in (root/'log').iterdir() if p.is_dir()),key=lambda x:x.stat().st_mtime)[-2:]
classes={
 'route_address_conflict':r'ROUTE_ERROR_ADDRESS_CONFLICT',
 'route_many_to_one':r'ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE',
 'route_source':r'ROUTE_ERROR_SOURCE_ROUTE_FAILURE',
 'route_non_tree':r'ROUTE_ERROR_NON_TREE_LINK_FAILURE',
 'join_or_interview':r'(?i)(device joined|interview started|starting interview|joining device|permit.join)',
 'leave':r'(?i)(device left|device leave|left the network)',
 'ota':r'(?i)(ota update|firmware update|update of .*firmware|zigbee.*update|updating firmware)',
 'owner_start':r'(?i)(zigbee.herdsman started|starting zigbee.herdsman|zigbee2mqtt started|starting zigbee2mqtt)',
 'adapter_reset':r'(?i)(adapter disconnected|ncpneedsreset|ncp needs reset|resetting ncp|ash reset)',
 'owner_error':r'(?i)(uncaught exception|unhandled rejection|error while starting|zigbee2mqtt failed)',
 'busy':r'(?i)(SLStatus.BUSY|EMBER_NETWORK_BUSY)',
 'failed_to':r'Failed to',
 'network_map':r'(?i)(networkmap|network map|mgmt_lqi|mgmt_rtg)',
}
patterns={name:re.compile(rx) for name,rx in classes.items()}
session_out=[]
for folder in folders:
 byminute=collections.defaultdict(collections.Counter); stamps=[]; total=0
 for f in folder.glob('*.log'):
  if f.stat().st_size>30_000_000:continue
  for line in f.open(errors='replace'):
   m=re.match(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d):\d\d\]',line)
   if not m:continue
   minute=m.group(1); total+=1; stamps.append(minute)
   for key,pattern in patterns.items():
    if pattern.search(line):byminute[minute][key]+=1
 minute_keys=sorted(byminute)
 # Do not publish raw events, addresses, device names, exception strings or payloads.
 if len(folders)>1 and folder==folders[0]: minute_keys=minute_keys[-8:]
 elif folder==folders[-1]: minute_keys=minute_keys[:8]
 session_out.append({'session':folder.name,'log_minutes': [min(stamps),max(stamps)] if stamps else [],
                     'lines':total,'categorized_minutes':{minute:dict(byminute[minute]) for minute in minute_keys}})
result={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sessions':session_out,'docker_events':[]}
try:
 until=datetime.datetime.now(datetime.timezone.utc).isoformat()
 p=subprocess.run(['docker','events','--since','2026-09-21T20:20:00Z','--until',until,'--format','{{json .}}'],capture_output=True,text=True,timeout=6)
 if p.returncode==0:
  for line in p.stdout.splitlines():
   try:event=json.loads(line)
   except ValueError:continue
   action=event.get('Action') or event.get('status') or ''
   actor=event.get('Actor') or {}; attrs=actor.get('Attributes') or {}
   if ('zigbee2mqtt' in str(attrs.get('name','')).lower() or 'zigbee2mqtt' in str(attrs.get('image','')).lower()) and action in ('start','die','kill','stop','restart','oom','destroy','create'):
    result['docker_events'].append({'utc':datetime.datetime.fromtimestamp(event.get('time',0),datetime.timezone.utc).isoformat(),'action':action})
except (FileNotFoundError,subprocess.TimeoutExpired): pass
print(json.dumps(result,sort_keys=True))
'''


def main():
    spec=importlib.util.spec_from_file_location('ha_readonly',HELPER)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    client=helper.connect('ha')
    try:
        _,out,err=client.exec_command('python3 -c '+shlex.quote(REMOTE),timeout=35)
        payload=out.read().decode('utf-8','replace');stderr=err.read().decode('utf-8','replace')
        if out.channel.recv_exit_status():raise RuntimeError('read-only timeline failed: '+stderr[:150])
        print(json.dumps(json.loads(payload),indent=2,sort_keys=True))
    finally:client.close()


if __name__=='__main__':main()
