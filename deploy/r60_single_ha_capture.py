#!/usr/bin/env python3
"""One SSH session, one read-only HA capture; retain raw logs only on the private laptop."""
import datetime
import importlib.util
import json
from pathlib import Path
import shlex
import tarfile

HELPER = Path(r'C:\Workspace\repos\config\skills\home-assistant-readonly\ha_readonly.py')
DEST = Path(r'C:\Workspace\.analienx\sonoff-private')
REMOTE = r'''import datetime, io, json, pathlib, subprocess, sys, tarfile, yaml
now=datetime.datetime.now(datetime.timezone.utc)
root=next((p for p in (pathlib.Path('/config/zigbee2mqtt'),pathlib.Path('/homeassistant/zigbee2mqtt')) if (p/'database.db').is_file() and (p/'configuration.yaml').is_file()),None)
if root is None: raise RuntimeError('Z2M files not found')
config=yaml.safe_load((root/'configuration.yaml').read_text()) or {}
advanced=config.get('advanced') or {}
serial=config.get('serial') or {}
meta={'captured_utc':now.isoformat(),'read_only':True,'db_mtime_utc':datetime.datetime.fromtimestamp((root/'database.db').stat().st_mtime,datetime.timezone.utc).isoformat(),
 'z2m_settings':{'channel':advanced.get('channel'),'transmit_power':advanced.get('transmit_power'),'log_level':advanced.get('log_level'),'serial_adapter':serial.get('adapter')},
 'owner':[],'docker_lifecycle_events':[],'included_files':[],'excluded_files':[],'errors':[]}
def run(args,seconds=12):
 try:
  p=subprocess.run(args,capture_output=True,text=True,timeout=seconds)
  if p.returncode: meta['errors'].append(args[1]+'_nonzero');return ''
  return p.stdout
 except (OSError,subprocess.TimeoutExpired):meta['errors'].append(args[1]+'_unavailable');return ''
for line in run(['docker','ps','--format','{{json .}}']).splitlines():
 try:d=json.loads(line)
 except ValueError:continue
 if 'zigbee2mqtt' not in (str(d.get('Names',''))+' '+str(d.get('Image',''))).lower():continue
 cid=d.get('ID')
 if not cid:continue
 details=run(['docker','inspect','--format','{{json .State}}',cid])
 try:s=json.loads(details)
 except ValueError:s={}
 meta['owner'].append({'container_short_id':cid,'image':d.get('Image'),'started_at':s.get('StartedAt'),'running':s.get('Running'),'restart_count_from_state':s.get('RestartCount')})
since=(now-datetime.timedelta(hours=72)).isoformat()
for line in run(['docker','events','--since',since,'--until',now.isoformat(),'--format','{{json .}}'],18).splitlines():
 try:e=json.loads(line)
 except ValueError:continue
 a=e.get('Action') or e.get('status') or '';attrs=(e.get('Actor') or {}).get('Attributes') or {}
 if a in ('kill','stop','die','destroy','create','start','restart','oom') and 'zigbee2mqtt' in (str(attrs.get('name',''))+' '+str(attrs.get('image',''))).lower():
  meta['docker_lifecycle_events'].append({'action':a,'utc':datetime.datetime.fromtimestamp(e.get('time',0),datetime.timezone.utc).isoformat()})
def add_bytes(tar,name,data):
 item=tarfile.TarInfo(name);item.size=len(data);item.mtime=int(now.timestamp());tar.addfile(item,io.BytesIO(data))
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz',compresslevel=5) as archive:
 db=(root/'database.db').read_bytes();add_bytes(archive,'private/database.db',db)
 meta['included_files'].append({'name':'private/database.db','original_size':len(db),'partial':False})
 for name in ('state.json',):
  f=root/name
  if f.is_file() and f.stat().st_size<20_000_000:
   data=f.read_bytes();add_bytes(archive,'private/'+name,data);meta['included_files'].append({'name':'private/'+name,'original_size':len(data),'partial':False})
 logroot=root/'log'; candidates=[]
 if logroot.is_dir():
  for f in logroot.rglob('*'):
   if f.is_file() and f.suffix.lower() in ('.log','.gz') and len(f.relative_to(logroot).parts)<=3:candidates.append(f)
 candidates.sort(key=lambda f:f.stat().st_mtime,reverse=True)
 total=0;limit=160_000_000;perfile=65_000_000
 for f in candidates:
  st=f.stat(); n=min(st.st_size,perfile,limit-total)
  if n<=0:meta['excluded_files'].append({'name':str(f.relative_to(logroot)),'reason':'capture_limit'});continue
  with f.open('rb') as stream:
   partial=st.st_size>n
   if partial:stream.seek(st.st_size-n)
   data=stream.read(n)
  name='private/log/'+f.relative_to(logroot).as_posix()
  add_bytes(archive,name,data)
  meta['included_files'].append({'name':name,'original_size':st.st_size,'captured_size':len(data),'partial':partial})
  total+=len(data)
 if not candidates:meta['errors'].append('no_log_files_found')
 # Docker stdout may contain lines absent from log files; bound to the most recent 12k lines.
 for owner in meta['owner'][:1]:
  raw=run(['docker','logs','--since',since,'--tail','12000','--timestamps',owner['container_short_id']],18)
  if raw:
   data=raw.encode('utf-8','replace')[-12_000_000:];add_bytes(archive,'private/docker_stdout_tail.log',data)
   meta['included_files'].append({'name':'private/docker_stdout_tail.log','captured_size':len(data),'partial':len(raw.encode('utf-8','replace'))>len(data)})
 add_bytes(archive,'capture_manifest.json',json.dumps(meta,sort_keys=True,indent=2).encode('utf-8'))
'''

def main():
    compile(REMOTE,'ha_capture_remote','exec')
    spec=importlib.util.spec_from_file_location('ha_readonly',HELPER)
    helper=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    DEST.mkdir(parents=True,exist_ok=True)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output=DEST/('r60_ha_one_pass_'+stamp+'.tar.gz')
    if output.exists():raise RuntimeError('will not overwrite prior evidence')
    client=helper.connect('ha')
    try:
        command='python3 -c '+shlex.quote(REMOTE)
        _stdin,stdout,stderr=client.exec_command(command,timeout=30)
        stdout.channel.settimeout(150)
        with output.open('xb') as saved:
            while True:
                chunk=stdout.read(65536)
                if not chunk:break
                saved.write(chunk)
        status=stdout.channel.recv_exit_status()
        if status:
            output.unlink(missing_ok=True)
            raise RuntimeError('one-pass HA capture failed; no retry performed (exit '+str(status)+')')
    finally:client.close()
    with tarfile.open(output,'r:gz') as bundle:
        manifest=json.load(bundle.extractfile('capture_manifest.json'))
    print(json.dumps({'archive_private_path':str(output),'archive_bytes':output.stat().st_size,
                      'captured_utc':manifest['captured_utc'],'owner':manifest['owner'],
                      'log_files':sum(x['name'].startswith('private/log/') for x in manifest['included_files']),
                      'partial_files':[x['name'] for x in manifest['included_files'] if x.get('partial')],
                      'excluded_files':manifest['excluded_files'],'errors':manifest['errors']},indent=2))

if __name__=='__main__':main()
