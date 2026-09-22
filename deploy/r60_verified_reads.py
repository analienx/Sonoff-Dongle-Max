#!/usr/bin/env python3
"""One fixed-cohort true-ZCL probe through the single Zigbee2MQTT owner.
The hash-pinned gate saves and removes its temporary extension; raw results stay local.
"""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from statistics import median
GATE=Path(r'C:\Workspace\worktrees\config-r60-owner-gate\supervisor\safety\r60_zcl_gate.py')
PRIVATE=Path(r'C:\Workspace\.analienx\sonoff-private')
def approved():
    import re
    path=PRIVATE/'r60_placement_before.json'
    if not path.is_file():raise RuntimeError('private_frozen_baseline_missing')
    old=json.loads(path.read_text(encoding='utf8'))['multizone_probe']['names']
    allow=re.compile(r'^(Hall|Kitchen|LivingRoom|Workroom|Bathroom|Toilet|Entry|Balcony|Nursery|Corridor|Utility)[A-Za-z0-9_]{2,70}$')
    exclude=re.compile(r'Bedroom|Circle|Workroom.*(?:Left|Right).*Dimmer|Workroom.*Dimmer.*(?:Left|Right)',re.I)
    names=[n for n in old if isinstance(n,str) and allow.fullmatch(n) and not exclude.search(n)]
    if not 8<=len(names)<=12 or len(set(names))!=len(names):raise RuntimeError('invalid_frozen_cohort')
    return names

def invoke(*args,timeout=350):
    p=subprocess.run([sys.executable,str(GATE),*args],capture_output=True,text=True,timeout=timeout)
    if p.returncode:raise RuntimeError('zcl_gate_failed; check private rollback status before retrying')
    try:return json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError,ValueError) as exc:raise RuntimeError('invalid_zcl_gate_reply') from exc

def summarize(data, required=None):
    results=data.get('results');names=data.get('names')
    expected=approved() if required is None else required
    if names!=expected or data.get('repeats')!=3 or not isinstance(results,list) or len(results)!=33:
        raise ValueError('invalid_exact_zcl_cohort')
    out=[]
    for i,n in enumerate(expected):
        three=[results[i+len(expected)*round] for round in range(3)]
        if any(x.get('name')!=n or x.get('round')!=round for round,x in enumerate(three)):
            raise ValueError('nonmatching_zcl_round')
        good=[x['latency_ms'] for x in three if x.get('status')=='zcl_verified' and isinstance(x.get('latency_ms'),int)]
        statuses=Counter(x.get('status') for x in three)
        addresses={x.get('network_address') for x in three if isinstance(x.get('network_address'),int)}
        out.append({'name':n,'network_address':next(iter(addresses)) if len(addresses)==1 else None,
                    'verified':len(good),'attempts':3,'median_ms':median(good) if good else None,
                    'statuses':dict(statuses)})
    return {'devices':out,'attempts':33,'verified':sum(x['verified'] for x in out),
            'all_devices_verified_at_least_once':all(x['verified']>=1 for x in out)}

def run():
    if not GATE.is_file():raise RuntimeError('missing_reviewed_zcl_gate')
    plan=invoke('plan',timeout=40)
    if plan.get('operation')!='z2m_r60_verified_zcl_read' or not plan.get('owner_epoch'):
        raise RuntimeError('invalid_owner_plan')
    public=invoke('execute',plan['plan_path'],plan['plan_hash'],timeout=340)
    if public.get('status')!='ok' or public.get('same_owner_epoch') is not True or public.get('extension_absent_after') is not True:
        raise RuntimeError('zcl_probe_incomplete_or_rollback_unverified')
    path=Path(public['private_result_path'])
    if not path.is_file() or 'sonoff-private' not in path.parts:raise RuntimeError('private_probe_missing')
    full=json.loads(path.read_text(encoding='utf-8'))
    if full.get('status')!='ok' or full.get('exit_code')!=0 or full.get('same_owner_epoch') is not True or full.get('extension_absent_after') is not True:
        raise RuntimeError('private_probe_or_rollback_failed')
    analysis=summarize(full['snapshot'],required=approved());analysis.update(owner_epoch=plan['owner_epoch'],private_result_path=str(path))
    return analysis
if __name__=='__main__':
    x=run();print(json.dumps(x,sort_keys=True))
