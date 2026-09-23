#!/usr/bin/env python3
"""Issue #28: bounded 10-minute, owner-only, read-only neighbor time series.
Uses the existing digest-pinned one-shot gate; saves full samples outside Git.
Each observation is an NCP table sample, NOT an eviction or on-air trace.
"""
import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from r60_placement_ab import snapshot, clear_audit
from r60_rf_window import load_private

PRIVATE = Path(r'C:\Workspace\.analienx\sonoff-private\issues\28-neighbor-mechanisms')
INTERVAL = 60
POINTS = 11

def summarize(rows):
    valid = [r for r in rows if r.get('status') == 'ok']
    transitions = []
    for a, b in zip(valid, valid[1:]):
        x = {e['longId'].lower(): e for e in load_private(a['snapshot'])['entries']}
        y = {e['longId'].lower(): e for e in load_private(b['snapshot'])['entries']}
        shared = x.keys() & y.keys()
        transitions.append({'departed': len(x.keys()-y.keys()), 'entered': len(y.keys()-x.keys()),
            'departed_prior_outcost_unknown': sum(x[k]['outCost']==0 for k in x.keys()-y.keys()),
            'departed_prior_age_over_six': sum(x[k]['age']>6 for k in x.keys()-y.keys()),
            'retained_outcost_changes': sum(x[k]['outCost']!=y[k]['outCost'] for k in shared),
            'retained_age_changes': sum(x[k]['age']!=y[k]['age'] for k in shared)})
    return {'samples': len(valid), 'intervals': len(transitions), 'transitions': transitions,
        'observed_departs': sum(t['departed'] for t in transitions),
        'unknown_outcost_before_departure': sum(t['departed_prior_outcost_unknown'] for t in transitions),
        'age_over_six_before_departure': sum(t['departed_prior_age_over_six'] for t in transitions),
        'note': 'One-minute snapshots miss intermediate events; repeated identity departures are not unique device failures.'}

def capture(seconds=600, interval=INTERVAL, points=POINTS, sampler=snapshot, sleeper=time.sleep,
            clock=time.monotonic):
    if seconds != 600 or interval != 60 or points != 11:
        raise ValueError('only_reviewed_600s_60s_11point_profile')
    PRIVATE.mkdir(parents=True, exist_ok=True)
    lock = PRIVATE / 'r60_neighbor_ten_min_active.lock'
    with lock.open('x', encoding='utf8') as handle:
        handle.write(datetime.now(timezone.utc).isoformat())
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    output = PRIVATE / ('r60_neighbor_ten_min_'+run_id+'.json')
    rows = []
    began = clock()
    failure = None
    try:
        for index in range(points):
            remaining = began + index*interval - clock()
            if remaining > 0: sleeper(remaining)
            if clock()-began > seconds+25: raise RuntimeError('sampling_deadline_exceeded')
            item = sampler()  # existing sole-owner, digest-pinned, install/read/remove gate
            if not item.get('owner_epoch') or item.get('count') != 26:
                raise RuntimeError('owner_or_full_neighbor_table_changed')
            if rows and item['owner_epoch'] != rows[0]['snapshot']['owner_epoch']:
                raise RuntimeError('owner_epoch_changed')
            load_private(item)  # rejects incomplete row and failed extension cleanup
            rows.append({'index': index, 'status': 'ok', 'snapshot': item})
            with output.open('w', encoding='utf8') as h:
                json.dump({'issue':28,'profile':'600s_60s_11points','complete':False,
                    'owner_epoch':rows[0]['snapshot']['owner_epoch'],'observations':rows},h,indent=2)
        if clock()-began > seconds+45: raise RuntimeError('capture_duration_exceeded')
    except Exception as exc:
        failure = type(exc).__name__+': '+str(exc)
    finally:
        summary = summarize(rows)
        payload = {'issue':28,'profile':'600s_60s_11points','complete':failure is None and len(rows)==points,
            'reason':failure,'observations':rows,'summary':summary}
        with output.open('w', encoding='utf8') as h: json.dump(payload,h,indent=2)
        lock.unlink()
    return output, payload

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture', 'report'))
    parser.add_argument('--file', type=Path, help='Existing private series for report')
    args = parser.parse_args()
    if args.action == 'capture':
        path, result = capture()
    else:
        if args.file is None or args.file.parent != PRIVATE or not args.file.is_file():
            parser.error('report requires an existing issue-28 private series file')
        path = args.file
        result = json.loads(path.read_text(encoding='utf8'))
    print(json.dumps({'issue':28,'complete':result['complete'], 'private_result':str(path),
        'reason':result.get('reason'),'summary':result['summary']},sort_keys=True))
    return 0 if result['complete'] else 2

if __name__ == '__main__': sys.exit(main())
