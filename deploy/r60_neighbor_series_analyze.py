#!/usr/bin/env python3
"""Issue #28: offline redacted transition analysis for the bounded ten-minute series."""
import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from r60_rf_window import load_private

PRIVATE = Path(r'C:\Workspace\.analienx\sonoff-private\issues\28-neighbor-mechanisms')
IDENTITY = re.compile(r'^[a-f0-9]{16}$')

def analyze(payload, read=load_private):
    if payload.get('issue') != 28 or not payload.get('complete'):
        raise ValueError('incomplete_issue28_capture')
    observations = payload.get('observations')
    if not isinstance(observations, list) or len(observations) != 11:
        raise ValueError('missing_or_extra_series_observations')
    rows, times, epochs = [], [], set()
    for number, entry in enumerate(observations):
        if entry.get('index') != number or entry.get('status') != 'ok':
            raise ValueError('missing_sample_or_changed_sequence')
        snap = entry['snapshot']
        epochs.add(snap['owner_epoch'])
        when = datetime.fromisoformat(snap['captured_utc'])
        times.append(when)
        data = read(snap)
        neighbors = data['entries']
        names = [str(e['longId']).lower() for e in neighbors]
        if len(neighbors) != 26 or len(set(names)) != 26 or not all(IDENTITY.fullmatch(n) for n in names):
            raise ValueError('incomplete_or_duplicate_neighbor_identity')
        if not all(isinstance(e.get('outCost'),int) and isinstance(e.get('age'),int)
                   and 0 <= e['outCost'] <= 7 and 0 <= e['age'] <= 255 for e in neighbors):
            raise ValueError('invalid_cost_or_age')
        rows.append({n: neighbor for n, neighbor in zip(names, neighbors)})
    if len(epochs) != 1:
        raise ValueError('changed_owner_epoch')
    gaps = [(b-a).total_seconds() for a,b in zip(times,times[1:])]
    if not all(40 <= d <= 85 for d in gaps):
        raise ValueError('noncomparable_sample_spacing')
    seen = Counter(n for row in rows for n in row)
    events = []
    departed_unknown = departed_known = departed_old = 0
    missing_reentered = set()
    returned = 0
    cost_known_to_unknown = cost_unknown_to_known = 0
    for minute,(old,new) in enumerate(zip(rows,rows[1:]),1):
        gone = old.keys()-new.keys()
        arrived = new.keys()-old.keys()
        common = old.keys()&new.keys()
        departed_unknown += sum(old[n]['outCost']==0 for n in gone)
        departed_known += sum(old[n]['outCost']!=0 for n in gone)
        departed_old += sum(old[n]['age']>6 for n in gone)
        cost_known_to_unknown += sum(old[n]['outCost']!=0 and new[n]['outCost']==0 for n in common)
        cost_unknown_to_known += sum(old[n]['outCost']==0 and new[n]['outCost']!=0 for n in common)
        returned_here = sum(any(n in prev for prev in rows[:minute-1]) for n in arrived)
        returned += returned_here
        missing_reentered.update(n for n in arrived if any(n in prev for prev in rows[:minute-1]))
        events.append({'offset_min':minute,'departed':len(gone),'entered':len(arrived),
            'departed_previous_outcost_unknown':sum(old[n]['outCost']==0 for n in gone),
            'departed_previous_age_over_six':sum(old[n]['age']>6 for n in gone),
            'returned_after_absence':returned_here,
            'retained_cost_changed':sum(old[n]['outCost']!=new[n]['outCost'] for n in common)})
    return {'issue':28,'sample_count':11,'sample_interval_seconds_min':round(min(gaps),1),
        'sample_interval_seconds_max':round(max(gaps),1),'unique_direct_neighbors_seen':len(seen),
        'neighbors_present_in_all_11':sum(n==11 for n in seen.values()),
        'observed_departure_events':departed_unknown+departed_known,
        'departed_previous_outcost_unknown':departed_unknown,'departed_previous_outcost_known':departed_known,
        'departed_previous_age_over_six':departed_old,
        'observed_return_events':returned,'unique_returned_neighbor_count':len(missing_reentered),
        'retained_cost_known_to_unknown':cost_known_to_unknown,
        'retained_cost_unknown_to_known':cost_unknown_to_known,
        'minute_by_minute':events,
        'limits':'60s samples miss intervening changes; these are observations, not independent devices, eviction causes, ACK traces or proved route failures.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    if args.path.parent != PRIVATE or not args.path.name.startswith('r60_neighbor_ten_min_'):
        parser.error('only an existing issue-28 private series is permitted')
    result=analyze(json.loads(args.path.read_text(encoding='utf8')))
    print(json.dumps(result,sort_keys=True,indent=2))

if __name__ == '__main__': main()
