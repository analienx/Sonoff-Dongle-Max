#!/usr/bin/env python3
"""One-command bounded A/B placement experiment. Never moves hardware or changes Zigbee settings.
Runs exact 11-device 3x ZCL cohort inside two read-only coordinator counter snapshots.
Old r60_placement_before.json is preserved unmodified and not used as a true-ZCL baseline.
"""
import argparse,json,sys,time
from datetime import datetime,timezone
from pathlib import Path
from r60_placement_ab import snapshot,window,clear_audit,intentionally_unpowered
from r60_verified_reads import run as verified,approved as approved_cohort
from r60_rf_window import compare as neighbor_compare,failure_firsthops
PRIVATE_ROOT=Path(r'C:\Workspace\.analienx\sonoff-private')
PRIVATE=PRIVATE_ROOT/'issues'/'27-placement'
def file(stage):return PRIVATE/('r60_placement_v2_'+stage+'.json')

def selected_after():
    for candidate in ('after_retry1','after'):
        path=file(candidate)
        if path.is_file():
            data=json.loads(path.read_text(encoding='utf8'))
            if data.get('valid') is True:return data
    raise RuntimeError('no_valid_after_attempt; rejected attempts preserved')
def summarize_delta(a,b):
    before,after=a['metrics'],b['metrics']
    keys=('mac_failure_fraction','mac_failure_per_min','neighbor_changes_per_min','cca_failures_per_min','mac_retries_per_min')
    change={k:round((after[k]/before[k]-1)*100,1) if before[k] else None for k in keys}
    traffic=after['mac_frames']/before['mac_frames']
    az,bz=a['zcl'],b['zcl']
    if [x['name'] for x in az['devices']]!=[x['name'] for x in bz['devices']]:raise ValueError('cohort_changed')
    regress=[p['name'] for p,q in zip(az['devices'],bz['devices']) if q['verified']<p['verified']]
    if not .5<=traffic<=2.0: verdict='inconclusive: background traffic differs >2x'
    elif regress:verdict='regression: same-device verified ZCL read success fell'
    elif change['mac_failure_fraction'] is not None and change['neighbor_changes_per_min'] is not None and change['mac_failure_fraction']<=-50 and change['neighbor_changes_per_min']<=-50:
        verdict='short-window RF improvement; repeat B and inspect device reads'
    elif change['mac_failure_fraction'] is not None and change['neighbor_changes_per_min'] is not None and change['mac_failure_fraction']>=25 and change['neighbor_changes_per_min']>=25:
        verdict='RF indicators worsened; check devices and consider restoring position'
    else:verdict='mixed or insufficient evidence; do not attribute cause'
    return {'verdict':verdict,'changes_percent':change,'traffic_ratio':round(traffic,3),
            'before_verified_zcl':az['verified'],'after_verified_zcl':bz['verified'],
            'regressed_devices':regress,'before_mac_failure':before['mac_failure_fraction'],
            'after_mac_failure':after['mac_failure_fraction'],
            'before_neighbor_changes_per_min':before['neighbor_changes_per_min'],
            'after_neighbor_changes_per_min':after['neighbor_changes_per_min']}
def stage(label, seconds, relocated):
    if not PRIVATE.is_dir():raise RuntimeError('issue27_private_evidence_folder_missing')
    if file(label).exists():raise RuntimeError('immutable_phase_already_exists')
    if label in ('after','after_retry1','confirm') and not relocated:raise RuntimeError('physical_relocation_not_confirmed')
    if label in ('after','after_retry1','confirm') and not file('before').is_file():raise RuntimeError('verified_before_missing')
    if label=='after_retry1':
        if not file('after').is_file():raise RuntimeError('rejected_after_missing')
        if json.loads(file('after').read_text(encoding='utf8')).get('valid') is not False:raise RuntimeError('retry_only_after_invalid_attempt')
    if label=='confirm':selected_after()
    if label=='before':
        legacy=PRIVATE_ROOT/'r60_placement_before.json'
        if not legacy.is_file():raise RuntimeError('legacy_placement_baseline_missing')
        previous=json.loads(legacy.read_text(encoding='utf8'))
        known={n for n in previous['multizone_probe']['names'] if not intentionally_unpowered(n)}
        if known!=set(approved_cohort()):raise RuntimeError('powered_cohort_changed_from_legacy_baseline')
    started=time.monotonic();first=snapshot();zcl=verified()
    if zcl['owner_epoch']!=first['owner_epoch']:raise RuntimeError('owner_changed_during_zcl_reads')
    time.sleep(max(0,started+seconds-time.monotonic()))
    second=snapshot()
    result={'phase':label,'physical_position':'original' if label=='before' else 'relocated_user_confirmed',
            'first':first,'second':second,'zcl':zcl}
    try:
        result['metrics']=window(first,second)
        result['clear_audit']=clear_audit(first,second)
        if result['clear_audit']['clear_markers']!=0:raise ValueError('hourly_counter_clear_detected')
        result['neighbors']=neighbor_compare(first,second)
        result['firsthop_groups']=failure_firsthops(zcl,first)
        result['valid']=True
    except (ValueError,RuntimeError,TimeoutError) as exc:
        result['valid']=False;result['reason']=str(exc)
    file(label).write_text(json.dumps(result,sort_keys=True,indent=2),encoding='utf8')
    print(json.dumps({'phase':label,'valid':result['valid'],'private_result':str(file(label)),
                      'metrics':result.get('metrics'),'zcl_verified':zcl['verified'],
                      'zcl_attempts':zcl['attempts'],'reason':result.get('reason')},sort_keys=True))
    if not result['valid']:raise SystemExit(2)
def report():
    before=json.loads(file('before').read_text(encoding='utf8'))
    after=selected_after()
    if not before.get('valid') or not after.get('valid'):raise RuntimeError('invalid_before_or_after')
    if before['first']['owner_epoch']!=after['first']['owner_epoch']:
        raise RuntimeError('owner_restarted_between_positions')
    outcome={'A_to_B':summarize_delta(before,after),'B_source_phase':after['phase'],'B_repeat':None,
             'note':'ZCL success is per-request owner-local endpoint.read. Cached first hop is indicative, not live RF trace. Placement also changes antenna geometry.'}
    if file('confirm').exists():
        repeat=json.loads(file('confirm').read_text(encoding='utf8'))
        if not repeat.get('valid') or repeat['first']['owner_epoch']!=after['first']['owner_epoch']:
            raise RuntimeError('invalid_B_repeat')
        outcome['B_repeat']=summarize_delta(after,repeat)
    print(json.dumps(outcome,indent=2,sort_keys=True))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('before','after','after_retry1','confirm','report'))
    p.add_argument('--seconds',type=int,default=300);p.add_argument('--relocated',action='store_true')
    a=p.parse_args()
    if a.action=='report':report()
    else:
        if not 240<=a.seconds<=600:p.error('window must be 240..600 seconds')
        stage(a.action,a.seconds,a.relocated)
if __name__=='__main__':main()
