#!/usr/bin/env python3
"""Issue #28: offline, identity-redacted join-window timeline from private Z2M logs."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

ROUTE = re.compile(r'ROUTE_ERROR_([A-Z_]+) for "([0-9]{1,5})"')
TARGET = re.compile(r'"target":([0-9]{1,5})')
PAIR_START = re.compile(r"z2m: Device '.*?' joined$")
PAIRED = 'device has successfully been paired'


def analyze(lines, excluded=()):
    """No raw log line, IEEE, NWK, or private friendly name leaves this function."""
    rows = [(line.split(chr(32), 1)[0], line) for line in lines if line.startswith(chr(50)+chr(48)) and len(line) > 20]
    starts = [ts for ts, line in rows if PAIR_START.search(line)]
    ends = [ts for ts, line in rows if PAIRED in line]
    start = starts[0] if starts else None
    end = next((ts for ts in ends if start is not None and ts >= start), None)
    targets = {int(m.group(1)) for ts, line in rows if start and end and start <= ts <= end
               and 'Interview - active endpoints request failed' in line for m in TARGET.finditer(line)}
    joining_nwk = next(iter(targets)) if len(targets) == 1 else None
    phases = {p:Counter() for p in ('pre_join','during_interview','post_interview')}
    errors_by_phase = {p:Counter() for p in phases}
    for ts, line in rows:
        phase = ('pre_join' if start is None or ts < start else
                 'during_interview' if end is None or ts <= end else 'post_interview')
        m = ROUTE.search(line)
        if m:
            phases[phase]['route_errors'] += 1
            errors_by_phase[phase][m.group(1)] += 1
            if joining_nwk is not None and int(m.group(2)) == joining_nwk:
                phases[phase]['route_errors_for_joining_nwk'] += 1
        if 'Interview - first modelId retrieval attempt failed' in line:
            phases[phase]['model_id_first_attempt_failed'] += 1
        if 'Interview - active endpoints request failed' in line:
            phases[phase]['active_endpoints_attempt_failed'] += 1
        if 'Successfully interviewed' in line and PAIRED in line:
            phases[phase]['interview_completed'] += 1
        if 'denied joining' in line.lower():
            phases[phase]['join_denied'] += 1
        if 'Failed to read state of ' in line:
            if any(name in line for name in excluded):
                phases[phase]['intentionally_unpowered_read_error'] += 1
            else:
                phases[phase]['other_read_error'] += 1
        if 'Starting Zigbee2MQTT' in line:
            phases[phase]['owner_start_logged'] += 1
    return {'join_started_utc':start,'join_completed_utc':end,
            'joining_nwk_resolved_privately': joining_nwk is not None,
            'log_first_utc': rows[0][0] if rows else None,
            'log_last_utc': rows[-1][0] if rows else None,
            'phases':{p:{'events':dict(phases[p]),'route_errors_by_type':dict(errors_by_phase[p])}
                      for p in phases},
            'limitations':['Z2M route-error NWK is a destination, not the MAC next hop.',
                'Passive logs do not include NCP counter deltas, neighbors or RF spectrum.',
                'No proof that joining caused contemporaneous route errors.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file',type=Path)
    parser.add_argument('--excluded-device',action='append',default=[])
    args=parser.parse_args()
    if 'sonoff-private' not in args.file.parts or not args.file.is_file():
        parser.error('private_issue_capture_required')
    result=analyze(args.file.read_text(encoding='utf8',errors='replace').splitlines(), args.excluded_device)
    print(json.dumps(result,sort_keys=True,indent=2))

if __name__=='__main__':main()
