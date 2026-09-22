#!/usr/bin/env python3
"""Bounded coordinator placement A/B. Run BEFORE moving, AFTER moving, then report.
Each stage makes two existing-owner, non-clearing NCP snapshots and a fixed multi-zone ZCL read cohort.
No second serial owner, database edit, log sweep, reset, or automatic firmware change.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

PRIVATE = Path(r'C:\Workspace\.analienx\sonoff-private')
GATE = Path(r'C:\Workspace\worktrees\config-r60-owner-gate\supervisor\safety\r60_z2m_neighbor_gate.py')
from r60_live_multizone_read import run as multizone_read
# Powered-off-by-design cohort: never use these as delivery or availability failures.
# A no-response from another device is still inconclusive unless power is confirmed.
import re

def intentionally_unpowered(name):
    return bool(re.search(r'^Bedroom.*Bulb|^LivingRoom.*Circle|^Workroom.*(?:Left|Right).*Dimmer|^Workroom.*Dimmer.*(?:Left|Right)', name, re.I))

FIELDS = ('MAC_TX_UNICAST_SUCCESS','MAC_TX_UNICAST_FAILED','MAC_TX_UNICAST_RETRY',
          'NEIGHBOR_ADDED','NEIGHBOR_REMOVED','NEIGHBOR_STALE','PHY_CCA_FAIL_COUNT',
          'APS_DATA_TX_UNICAST_SUCCESS','APS_DATA_TX_UNICAST_FAILED',
          'ROUTE_DISCOVERY_INITIATED','BROADCAST_TABLE_FULL',
          'ALLOCATE_PACKET_BUFFER_FAILURE','PHY_TO_MAC_QUEUE_LIMIT_REACHED',
          'TYPE_NWK_RETRY_OVERFLOW','ASH_OVERFLOW_ERROR','ASH_FRAMING_ERROR','ASH_OVERRUN_ERROR')

def invoke(script: Path, *args: str, timeout=75):
    if not script.is_file(): raise RuntimeError('required_local_script_missing')
    p = subprocess.run([sys.executable, str(script), *args], capture_output=True,
                       text=True, timeout=timeout, check=False)
    if p.returncode: raise RuntimeError(f'{script.name} exited {p.returncode}; no live mutation is retried')
    try: return json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError) as exc: raise RuntimeError('invalid_probe_reply') from exc

def snapshot():
    plan = invoke(GATE, 'plan', timeout=40)
    if plan.get('operation') != 'z2m_r60_neighbor_snapshot' or not plan.get('owner_epoch'):
        raise RuntimeError('plan_owner_invariant_failed')
    result = invoke(GATE, 'execute', plan['plan_path'], plan['plan_hash'], timeout=80)
    if result.get('status') != 'ok' or result.get('same_owner_epoch') is not True or result.get('extension_absent_after') is not True:
        raise RuntimeError('snapshot_or_extension_removal_failed')
    if not all(isinstance(result.get('counters', {}).get(k), int) for k in FIELDS):
        raise RuntimeError('incomplete_ncp_counters')
    return {'owner_epoch':plan['owner_epoch'], 'captured_utc':datetime.now(timezone.utc).isoformat(),
            'count':result['count'], 'source_route_filled':result.get('source_route_filled'),
            'counters':{k:result['counters'][k] for k in FIELDS},
            'private_result_path':result['private_result_path']}

def window(a, b):
    if a['owner_epoch'] != b['owner_epoch']: raise ValueError('owner_restarted_in_window')
    duration=(datetime.fromisoformat(b['captured_utc'])-datetime.fromisoformat(a['captured_utc'])).total_seconds()
    if not 45 <= duration <= 900: raise ValueError('invalid_window_duration')
    counts={k:b['counters'][k]-a['counters'][k] for k in FIELDS}
    if any(x < 0 for x in counts.values()): raise ValueError('ncp_counter_reset_or_wrap; discard_window')
    tx=counts['MAC_TX_UNICAST_SUCCESS']+counts['MAC_TX_UNICAST_FAILED']
    if tx < 20: raise ValueError('too_few_mac_outcomes_for_comparison')
    return {'seconds':round(duration,1),'mac_frames':tx, 'mac_failure_fraction':round(counts['MAC_TX_UNICAST_FAILED']/tx,5),
            'mac_failure_per_min':round(counts['MAC_TX_UNICAST_FAILED']*60/duration,3),
            'neighbor_changes_per_min':round((counts['NEIGHBOR_ADDED']+counts['NEIGHBOR_REMOVED'])*60/duration,3),
            'cca_failures_per_min':round(counts['PHY_CCA_FAIL_COUNT']*60/duration,3),
            'mac_retries_per_min':round(counts['MAC_TX_UNICAST_RETRY']*60/duration,3),
            'aps_failures':counts['APS_DATA_TX_UNICAST_FAILED'], 'route_discoveries':counts['ROUTE_DISCOVERY_INITIATED'],
            'resource_failure_events':sum(counts[k] for k in ('BROADCAST_TABLE_FULL','ALLOCATE_PACKET_BUFFER_FAILURE',
                'PHY_TO_MAC_QUEUE_LIMIT_REACHED','TYPE_NWK_RETRY_OVERFLOW','ASH_OVERFLOW_ERROR','ASH_FRAMING_ERROR','ASH_OVERRUN_ERROR')),
            'counter_deltas':counts}

def stage(phase, seconds):
    PRIVATE.mkdir(parents=True, exist_ok=True)
    path=PRIVATE/f'r60_placement_{phase}.json'
    if path.exists(): raise RuntimeError(f'{phase} already exists: do not overwrite an A/B phase')
    if phase=='after' and not (PRIVATE/'r60_placement_before.json').exists():
        raise RuntimeError('run before first, while dongle is still in original position')
    begun=time.monotonic()
    first=snapshot()
    # Freeze a fixed, geographically distributed set of powered router names at baseline.
    frozen = None
    if phase == 'after':
        previous=json.loads((PRIVATE/'r60_placement_before.json').read_text(encoding='utf8'))
        if not previous.get('valid') or not previous.get('multizone_probe',{}).get('names'):
            raise RuntimeError('missing_valid_multizone_baseline')
        frozen=[n for n in previous['multizone_probe']['names'] if not intentionally_unpowered(n)]
        if len(frozen)<8:
            raise RuntimeError('insufficient_confirmed_powered_baseline_targets')
    probe=multizone_read(frozen)
    if probe['status']!='complete' or probe['same_owner_epoch'] is not True:
        raise RuntimeError('multizone_sample_failed')
    if first['owner_epoch']!=probe['owner_epoch']:
        raise RuntimeError('owner_changed_between_ncp_and_zcl')
    time.sleep(max(0.0, begun+seconds-time.monotonic()))
    second=snapshot()
    result={'phase':phase,'setup':'unchanged original placement' if phase=='before' else 'dongle relocated; unchanged firmware/channel/TX',
            'started_utc':first['captured_utc'],'finished_utc':second['captured_utc'],
            'first':first,'second':second,'multizone_probe':probe}
    try: result['metrics']=window(first,second);result['valid']=True
    except ValueError as exc: result['valid']=False;result['reason']=str(exc)
    with path.open('x',encoding='utf8') as out: json.dump(result,out,indent=2,sort_keys=True)
    print(json.dumps({'phase':phase,'valid':result['valid'],'metrics':result.get('metrics'),
                      'multizone_sample':{'count':len(probe['names']),'zones':probe['zone_count'],'responses':sum(x['status']=='fresh_state' for x in probe['results'])},'private_path':str(path),'reason':result.get('reason')},sort_keys=True))
    if not result['valid']: raise SystemExit(2)

def report():
    before=json.loads((PRIVATE/'r60_placement_before.json').read_text(encoding='utf8'))
    after=json.loads((PRIVATE/'r60_placement_after.json').read_text(encoding='utf8'))
    if not before.get('valid') or not after.get('valid'): raise RuntimeError('invalid_comparison_window')
    a,b=before['metrics'],after['metrics']
    metrics=('mac_failure_fraction','mac_failure_per_min','neighbor_changes_per_min','cca_failures_per_min','mac_retries_per_min')
    changes={k:round((b[k]/a[k]-1)*100,1) if a[k] else None for k in metrics}
    load=b['mac_frames']/a['mac_frames']
    if not .5 <= load <= 2.0: verdict='inconclusive: MAC traffic differs by >2x'
    elif (changes['mac_failure_fraction'] is not None and changes['neighbor_changes_per_min'] is not None and
          changes['mac_failure_fraction'] <= -50 and changes['neighbor_changes_per_min'] <= -50):
        verdict='strong short-window improvement; repeat under ordinary household traffic before declaring fixed'
    elif (changes['mac_failure_fraction'] is not None and changes['neighbor_changes_per_min'] is not None and
          changes['mac_failure_fraction'] >= 25 and changes['neighbor_changes_per_min'] >= 25):
        verdict='both indicators worse; restore prior placement if devices are affected'
    else: verdict='mixed/insufficient evidence; do not attribute cause from this short comparison'
    pa,pb=before['multizone_probe'],after['multizone_probe']
    eligible=[n for n in pa.get('names',[]) if not intentionally_unpowered(n)]
    if eligible!=pb.get('names') or pa.get('zone_count',0)<4:
        raise RuntimeError('device_cohort_changed_between_placements')
    def outcome(p):
        outcomes=[x for x in p['results'] if x['name'] in eligible];success=[x for x in outcomes if x['status']=='fresh_state']
        timings=sorted(x['latency_ms'] for x in success)
        return {'attempted':len(outcomes),'verified_fresh':len(success),
                'success_fraction':round(len(success)/len(outcomes),3),
                'p50_latency_ms':timings[len(timings)//2] if timings else None,
                'failures':[x['name'] for x in outcomes if x['status']!='fresh_state']}
    before_out,after_out=outcome(pa),outcome(pb)
    if pa.get('owner_epoch')!=pb.get('owner_epoch'):
        verdict='inconclusive: owner changed between placement stages'
    if pa.get('same_owner_epoch') is not True or pb.get('same_owner_epoch') is not True:
        verdict='inconclusive: Zigbee2MQTT restarted during multi-zone sample'
    if after_out['verified_fresh']<before_out['verified_fresh']:
        verdict+='; multi-zone device success regressed'
    if before_out['verified_fresh']<8 or after_out['verified_fresh']<8:
        verdict+='; insufficient verified multi-zone responses for a reliability claim'
    print(json.dumps({'verdict':verdict,'relative_changes_pct':changes,'traffic_ratio_after_before':round(load,3),
        'before':{k:a[k] for k in metrics},'after':{k:b[k] for k in metrics},
        'before_devices':before_out,'after_devices':after_out,'fixed_sample_names':eligible,
        'excluded_by_design':[n for n in pa['names'] if intentionally_unpowered(n)],
        'note':'Fresh non-retained states are device-response proxies, not proof of correlated ZCL read; room diversity does not prove distinct router paths. MAC outcomes are radio frames, not household commands. Placement A/B does not isolate USB3 noise from antenna geometry.'},indent=2))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=('before','after','report'))
    ap.add_argument('--seconds',type=int,default=180,help='per-position window: 120..600 seconds (default 180)')
    args=ap.parse_args()
    if args.action=='report':report()
    else:
        if not 120<=args.seconds<=600:ap.error('seconds must be 120..600')
        stage(args.action,args.seconds)
if __name__=='__main__':main()
