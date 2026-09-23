#!/usr/bin/env python3
"""Analyze one private R60 HA capture offline, without another HA access or public raw logs."""
import collections
import datetime
import glob
import json
from pathlib import Path
import re
import tarfile

DEST = Path(r'C:\Workspace\.analienx\sonoff-private')
ROUTE = re.compile(r'ROUTE_ERROR_([A-Z_]+) for ["\']?(\d+)')
TIMESTAMP = re.compile(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]')
START = re.compile(r'(?i)(starting zigbee2mqtt|zigbee2mqtt started|starting zigbee.herdsman|zigbee.herdsman started|successfully started)')
FAILURE = re.compile(r'(?i)(failed to (send|read|write|publish|configure|interview|execute)|timed out|timeout|MAC_NO_ACK|NO_ACK|DELIVERY_FAILED|ASH.*(error|reset)|SLStatus.BUSY|EMBER_NETWORK_BUSY)')
COMMAND = re.compile(r'(?i)(failed to (send|read|write)|delivery_failed|mac_no_ack|no_ack|command.*(failed|timeout)|send.*failed)')
JOIN = re.compile(r'(?i)(device joined|joined the network|device left|leave.*network|interview started|starting interview)')
MAP = re.compile(r'(?i)(networkmap|network map|mgmt_lqi|mgmt_rtg|lqi.*failed|routing table.*failed)')
OTA = re.compile(r'(?i)(ota updating|firmware transfer|update progress|image block request|OTA update (completed|failed)|firmware update (started|completed|failed))')
BUSY = re.compile(r'(?i)(SLStatus.BUSY|EMBER_NETWORK_BUSY|EZSP.*BUSY|status.*BUSY)')

def main():
    files = sorted(DEST.glob('r60_ha_one_pass_*.tar.gz'))
    if len(files) != 1:
        raise RuntimeError('Select an exact capture: expected one local archive, found '+str(len(files)))
    with tarfile.open(files[0], 'r:gz') as archive:
        manifest = json.load(archive.extractfile('capture_manifest.json'))
        db = {}
        for line in archive.extractfile('private/database.db'):
            try: item = json.loads(line)
            except (ValueError,UnicodeDecodeError): continue
            nwk=item.get('nwkAddr')
            if isinstance(nwk,int):db[nwk]=item
        role_counts=collections.Counter(item.get('type','unknown') for item in db.values())
        sessions={}; aggregate=collections.Counter(); total_lines=0; failures=collections.Counter()
        route_by_device=collections.Counter(); route_by_session=collections.defaultdict(collections.Counter)
        first_last={}; hourly=collections.defaultdict(collections.Counter); interesting=[]; all_starts=[]
        logs=sorted((m for m in archive.getmembers() if m.name.startswith('private/log/') and m.name.endswith('.log')),key=lambda m:m.name)
        for member in logs:
            session=member.name.split('/')[2]
            info=sessions.setdefault(session,{'files':0,'lines':0,'errors':collections.Counter(),'first':None,'last':None,'failures':0,'commands':0,'starts':0,'joins':0,'maps':0,'ota_transfers':0,'busy':0})
            info['files']+=1
            with archive.extractfile(member) as stream:
                for raw in stream:
                    text=raw.decode('utf-8','replace').rstrip('\r\n');info['lines']+=1;total_lines+=1
                    match=TIMESTAMP.match(text)
                    stamp=match.group(1) if match else None
                    if stamp:
                        info['first']=min(info['first'],stamp) if info['first'] else stamp
                        info['last']=max(info['last'],stamp) if info['last'] else stamp
                    route=ROUTE.search(text)
                    if route:
                        kind,nwk=route.group(1),int(route.group(2))
                        info['errors'][kind]+=1; aggregate[kind]+=1;route_by_device[(kind,nwk)]+=1;route_by_session[session][kind]+=1
                        if stamp:hourly[stamp[:13]][kind]+=1
                    if FAILURE.search(text):
                        info['failures']+=1
                        key=re.sub(r'\b\d+\b','N',re.sub(r'(?i)0x[0-9a-f]{16}','[ID]',text.split('zh:')[-1]))[:120]
                        failures[key]+=1
                        if len(interesting)<35 and stamp and (COMMAND.search(text) or BUSY.search(text)):
                            interesting.append({'at':stamp,'session':session,'category':'command_or_busy'})
                    if COMMAND.search(text):info['commands']+=1
                    if BUSY.search(text):info['busy']+=1
                    if START.search(text):info['starts']+=1;all_starts.append({'session':session,'timestamp':stamp})
                    if JOIN.search(text):info['joins']+=1
                    if MAP.search(text):info['maps']+=1
                    if OTA.search(text):info['ota_transfers']+=1
        summary={'capture_utc':manifest['captured_utc'],'settings':manifest['z2m_settings'],
                 'owner':manifest['owner'],'docker_lifecycle_events':manifest['docker_lifecycle_events'],
                 'archive_bytes':files[0].stat().st_size,'database_roles':dict(role_counts),
                 'database_records':len(db),'log_files':len(logs),'log_lines':total_lines,
                 'session_count':len(sessions),'route_error_total':sum(aggregate.values()),'route_error_by_type':dict(aggregate),
                 'sessions':{s:{**{k:v for k,v in info.items() if k!='errors'},'errors':dict(info['errors'])} for s,info in sorted(sessions.items())},
                 'hourly_route_errors':{k:dict(v) for k,v in sorted(hourly.items())},
                 'top_route_error_targets':[{'reason':reason,'nwk':nwk,'device_type':db.get(nwk,{}).get('type'),
                      'model':db.get(nwk,{}).get('modelId'),'count':n} for (reason,nwk),n in route_by_device.most_common(20)],
                 'possible_command_failure_lines':sum(i['commands'] for i in sessions.values()),
                 'busy_lines':sum(i['busy'] for i in sessions.values()),
                 'map_lines':sum(i['maps'] for i in sessions.values()),
                 'ota_transfer_lines':sum(i['ota_transfers'] for i in sessions.values()),
                 'all_starts':all_starts[:30], 'limitations':['Log line counts are not unique failed commands, packet rates, active-router counts or root-cause proof.',
                 'Log timestamps use the HA configured local clock; owner Docker timestamps are UTC.',
                 'DB NWK identifiers can change, so current device association is provisional for old log lines.',
                 'Raw logs and device identifiers remain only in the private laptop archive.']}
    report=DEST/(files[0].stem.replace('.tar','')+'_analysis.json')
    with report.open('x',encoding='utf-8') as out:json.dump(summary,out,indent=2,sort_keys=True)
    print('LOCAL_ANALYSIS_FILE='+str(report))
    print(json.dumps(summary,indent=2,sort_keys=True))

if __name__=='__main__':main()
