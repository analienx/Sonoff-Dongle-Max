#!/usr/bin/env python3
"""Read-only, identifier-free OTA activity classification for last two Z2M log sessions."""
import importlib.util
import json
from pathlib import Path
import shlex

HELPER=Path(r'C:\Workspace\repos\config\skills\home-assistant-readonly\ha_readonly.py')
REMOTE=r'''import collections,datetime,json,pathlib,re
root=next((p for p in (pathlib.Path('/config/zigbee2mqtt'),pathlib.Path('/homeassistant/zigbee2mqtt')) if (p/'log').exists()),None)
if root is None:raise RuntimeError('Z2M log root missing')
dirs=sorted((d for d in (root/'log').iterdir() if d.is_dir()),key=lambda d:d.stat().st_mtime)[-2:]
rx={
 'ota_available_or_check':r'(?i)(checking if OTA update available|OTA update available|no OTA update available|requested OTA|responded to OTA request)',
 'ota_transfer_start':r'(?i)(OTA updating .{0,120} to |Updating .{0,120} to (latest|previous|.*firmware)|firmware update started)',
 'ota_transfer_progress':r'(?i)(OTA update progress|firmware update progress|image block request|update progress.*%)',
 'ota_transfer_finish':r'(?i)(OTA update of .{0,120} failed|Update of .{0,120} (completed|failed|successful)|firmware update completed)',
 'ota_other_explicit':r'(?i)(\bOTA\b|firmware\s+update)',
}
patterns={k:re.compile(p) for k,p in rx.items()}
answer=[]
for directory in dirs:
 counts=collections.defaultdict(collections.Counter)
 for f in directory.glob('*.log'):
  if f.stat().st_size>30_000_000:continue
  for line in f.open(errors='replace'):
   m=re.match(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d):\d\d\]',line)
   if not m:continue
   minute=m.group(1)
   for key,pat in patterns.items():
    if pat.search(line):counts[minute][key]+=1
 keys=sorted(counts)
 if directory==dirs[0]:keys=keys[-15:]
 else:keys=keys[:15]
 answer.append({'session':directory.name,'per_minute':{k:dict(counts[k]) for k in keys}})
print(json.dumps({'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'sessions':answer, 'note':'OTA availability/check references do NOT establish active firmware transfer'},sort_keys=True))
'''

def main():
    spec=importlib.util.spec_from_file_location('ha_readonly',HELPER)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    client=helper.connect('ha')
    try:
        _,out,err=client.exec_command('python3 -c '+shlex.quote(REMOTE),timeout=30)
        payload=out.read().decode('utf-8','replace');stderr=err.read().decode('utf-8','replace')
        if out.channel.recv_exit_status():raise RuntimeError('passive OTA classification failed: '+stderr[:120])
        print(json.dumps(json.loads(payload),indent=2,sort_keys=True))
    finally:client.close()

if __name__=='__main__':main()
