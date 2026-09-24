"""Deferred HA USB P10 handoff after Zigbee2MQTT stop and SONOFF disconnect.

Only enumerates HA by-id paths, probes an idle selected port with ZNP ping/version
and stages PRIVATE two-layer configs. No radio NV/IEEE/network or live HA writes.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import shlex
import sys
import zipfile
import yaml
from p10_cutover_prepare import private_target
from p10_data_bundle import verify,load_ha,addon_info,OPTIONS_NAME
from p10_ha_state import addon_quiescent
from p10_migration_workflow import stage as stage_source,_write

EXPECTED_REVISION=20260310  # Revision measured on the selected idle P10; NOT an IEEE/network proof.
REMOTE=r'''
import json,os,pathlib,select,sys,termios,time,tty,fcntl
source=sys.argv[1]; chosen=sys.argv[2] if len(sys.argv)>2 else ''
base=pathlib.Path('/dev/serial/by-id')
if not base.is_dir(): raise RuntimeError('No stable by-id serial directory on HA')
ports=sorted(str(p) for p in base.iterdir() if p.is_symlink() and p.exists()
             and os.path.realpath(p).startswith(('/dev/ttyUSB','/dev/ttyACM')))
if source in ports or os.path.exists(source):
 raise RuntimeError('Original SONOFF USB interface is still present')
result={'source_usb_absent':True,'available_usb_by_id':ports,'znp_p10_verified':False}
if chosen:
 if chosen not in ports or chosen==source:
  raise RuntimeError('Selected target is not a distinct available HA by-id USB port')
 fd=os.open(chosen,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
 try:
  fcntl.ioctl(fd,getattr(termios,'TIOCEXCL',0x540C))
  original=termios.tcgetattr(fd)
  tty.setraw(fd,termios.TCSANOW)  # Binary ZNP frames contain no newline.
  settings=termios.tcgetattr(fd)
  settings[4]=termios.B115200;settings[5]=termios.B115200
  settings[2]=(settings[2]|termios.CLOCAL|termios.CREAD)&~getattr(termios,'CRTSCTS',0)
  settings[6][termios.VMIN]=0;settings[6][termios.VTIME]=0
  termios.tcsetattr(fd,termios.TCSANOW,settings)
  termios.tcflush(fd,termios.TCIFLUSH)
  def command(code):
   body=bytes((0,0x21,code));checksum=0
   for byte in body: checksum^=byte
   os.write(fd,b'\xfe'+body+bytes((checksum,)))
   deadline=time.monotonic()+5;buffer=bytearray()
   while time.monotonic()<deadline:
    readable,_,_=select.select([fd],[],[],0.25)
    if readable:
     try:buffer.extend(os.read(fd,256))
     except BlockingIOError:pass
    while buffer and buffer[0]!=0xfe:del buffer[0]
    while len(buffer)>=5:
     n=buffer[1]
     if n>64:del buffer[0];break
     if len(buffer)<n+5:break
     frame=bytes(buffer[:n+5]);del buffer[:n+5]
     check=0
     for byte in frame[1:]:check^=byte
     if check or frame[2]!=0x61 or frame[3]!=code:continue
     return frame[4:-1]
   raise TimeoutError('No valid P10 ZNP ping/version response')
  ping=command(1);version=command(2)
  if len(ping)!=2 or len(version) not in (9,10) or version[1]!=1:
   raise RuntimeError('USB device is not the expected ZNP firmware')
  result.update({'znp_p10_verified':True,'verified_target_by_id':chosen,
                 'product':version[1],'revision':int.from_bytes(version[5:9],'little')})
 finally:
  try:termios.tcsetattr(fd,termios.TCSANOW,original)
  except (OSError,UnboundLocalError):pass
  os.close(fd)
print(json.dumps(result,sort_keys=True))
'''


def source_serial(bundle:Path)->tuple[bytes,dict,dict,str]:
    checked=verify(private_target(bundle))
    if checked.get('cold_consistent') is not True or checked.get('integrity_pass') is not True:
        raise RuntimeError('Verified final COLD application bundle required before USB handoff')
    with zipfile.ZipFile(bundle) as archive:
        raw=archive.read('data/configuration.yaml')
        wrapper=json.loads(archive.read(OPTIONS_NAME))
    config=yaml.safe_load(raw)
    if not isinstance(config,dict) or not isinstance(config.get('serial'),dict):
        raise RuntimeError('Invalid source serial configuration')
    old=config['serial'];path=old.get('port')
    if old.get('adapter')!='ember' or not isinstance(path,str) or not path.startswith('/dev/serial/by-id/'):
        raise RuntimeError('Expected original SONOFF Ember by-id USB source')
    if wrapper['options'].get('serial',{}).get('port')!=path or wrapper['options']['serial'].get('adapter')!='ember':
        raise RuntimeError('Source add-on options and Zigbee2MQTT YAML serial disagree')
    return raw,config,wrapper,path


def discover(bundle:Path,selected:str|None=None,expected_revision:int=EXPECTED_REVISION)->dict:
    _,_,_,source=source_serial(bundle)
    if selected and not re.fullmatch(r'/dev/serial/by-id/[A-Za-z0-9_.+:-]+',selected):
        raise ValueError('Select an exact HA USB by-id path; never COM4 or ttyACM0')
    client=load_ha()
    try:
        quiescence=addon_quiescent(client, addon_info(client))  # Error allowed only with exited Docker container.
        cmd='python3 -c '+shlex.quote(REMOTE)+' '+shlex.quote(source)
        if selected:cmd+=' '+shlex.quote(selected)
        _,stdout,_=client.exec_command(cmd,timeout=22)
        response=stdout.read().decode('utf-8')
        if stdout.channel.recv_exit_status()!=0:
            raise RuntimeError('USB scan failed or SONOFF USB still detected; keep Zigbee2MQTT stopped')
        result=json.loads(response)
        if result.get('source_usb_absent') is not True:
            raise RuntimeError('Original SONOFF USB absence not proven')
        if selected and (result.get('verified_target_by_id')!=selected or
                         result.get('znp_p10_verified') is not True or
                         result.get('revision')!=expected_revision or result.get('product')!=1):
            raise RuntimeError('Selected USB interface is not the previously measured P10 ZNP firmware revision')
        return result|quiescence|{'addon_stopped':True,'network_restore_verified':False,
                       'sonoff_power_isolation_verified_by_software':False}
    finally:client.close()


def usb_yaml(raw:bytes,selected:str)->bytes:
    if not re.fullmatch(r'/dev/serial/by-id/[A-Za-z0-9_.+:-]+',selected):
        raise ValueError('Invalid immutable HA USB by-id path')
    original=yaml.safe_load(raw);expected=deepcopy(original)
    expected['serial']['port']=selected;expected['serial']['adapter']='zstack'
    lines=raw.decode('utf-8').splitlines(keepends=True)
    heads=[i for i,line in enumerate(lines) if re.fullmatch(r'serial:\s*(?:#.*)?\r?\n?',line)]
    if len(heads)!=1:raise ValueError('Expected exactly one root serial YAML block')
    start=heads[0]+1
    stop=next((i for i in range(start,len(lines)) if lines[i].strip() and
               not lines[i][0].isspace() and not lines[i].lstrip().startswith('#')),len(lines))
    for key,value in (('port',selected),('adapter','zstack')):
        matches=[(i,m) for i in range(start,stop)
                 if (m:=re.fullmatch(r'  '+key+r':[^\r\n]*(\r?\n?)',lines[i]))]
        if len(matches)!=1:raise ValueError('Expected exactly one direct serial.'+key+' line')
        i,m=matches[0];lines[i]='  '+key+': '+value+m.group(1)
    proposed=''.join(lines).encode('utf-8')
    if yaml.safe_load(proposed)!=expected:
        raise RuntimeError('USB rendering changed fields other than port/adapter')
    return proposed


def stage_usb(bundle:Path,out:Path,target:str,expected_revision:int=EXPECTED_REVISION)->dict:
    raw,_,wrapper,_=source_serial(bundle)
    proposed=usb_yaml(raw,target)
    options=deepcopy(wrapper)
    options['options']['serial']['port']=target;options['options']['serial']['adapter']='zstack'
    if yaml.safe_load(proposed)['serial']!=options['options']['serial']:
        raise RuntimeError('USB YAML and Supervisor options serial fields disagree')
    found=discover(bundle,target,expected_revision)
    if found.get('znp_p10_verified') is not True:raise RuntimeError('P10 USB probe not verified')
    out=private_target(out)
    stage_source(bundle,out)  # Cold bundle, source recovery files and private device baseline.
    hashes={'target_configuration.yaml':_write(out/'target_configuration.yaml',proposed),
            'target_addon_options.private.json':_write(out/'target_addon_options.private.json',
                                       json.dumps(options,indent=2,sort_keys=True).encode())}
    statefile=out/'cutover_state.private.json'
    state=json.loads(statefile.read_text(encoding='utf-8'))
    state['rollback_and_target_hashes'].update(hashes)
    state.update({'target_znp_verified_from_ha':True,'target_interface':'usb',
                  'verified_usb_by_id':target,'verified_p10_revision':expected_revision,
                  'target_verified_at_utc':datetime.now(timezone.utc).isoformat(),
                  'source_usb_absent_at_probe':True,'network_restore_implemented':False,
                  'migration_authorized':False})
    statefile.write_text(json.dumps(state,indent=2,sort_keys=True),encoding='utf-8')
    return {'status':'USB_TARGET_CONFIG_STAGED_NOT_DEPLOYED','source_usb_absent_at_probe':True,
            'target_interface':'usb','znp_p10_verified':True,'target_by_id':target,
            'source_cold_bundle_verified':True,'sonoff_power_isolation_verified_by_software':False,
            'network_restored':False,'application_config_changed':False}


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='action',required=True)
    d=commands.add_parser('discover');d.add_argument('--cold-bundle',type=Path,required=True)
    s=commands.add_parser('stage');s.add_argument('--cold-bundle',type=Path,required=True)
    s.add_argument('--out',type=Path,required=True);s.add_argument('--target-by-id',required=True)
    for task in (d,s):task.add_argument('--expected-revision',type=int,default=EXPECTED_REVISION)
    args=parser.parse_args(argv)
    try:
        result=(discover(args.cold_bundle,expected_revision=args.expected_revision)
                if args.action=='discover' else
                stage_usb(args.cold_bundle,args.out,args.target_by_id,args.expected_revision))
        print(json.dumps(result,sort_keys=True,indent=2));return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,zipfile.BadZipFile) as exc:
        print('P10_USB_CUTOVER_ERROR: '+str(exc)[:160],file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
