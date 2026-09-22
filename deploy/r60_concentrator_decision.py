#!/usr/bin/env python3
"""One-shot offline concentrator triage. Reads ONLY the previously saved private HA archive.

Usage: py -3 deploy/r60_concentrator_decision.py C:\\...\\r60_ha_one_pass_20260922T070247Z.tar.gz
No HA/network calls, writes, IEEE addresses, passwords or raw lines in output.
"""
import collections
import json
import re
import sys
import tarfile

ROUTE = re.compile(r'ROUTE_ERROR_([A-Z_]+) for "\d+"')
STAMP = re.compile(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]')
SETFAIL = re.compile(r"Failed to publish.*(?:/set|Publish 'set')|Publish 'set'.*failed", re.I)
STACK = re.compile(r'Using stack config\s+(\{[^\r\n]*\})')
START = '[CONCENTRATOR] Started source route discovery.'


def inspect(lines):
    result = {'lines': 0, 'route_errors': collections.Counter(), 'set_failure_lines': 0,
              'stack_configs': [], 'concentrator_start_lines': 0, 'first': None, 'last': None}
    for line in lines:
        result['lines'] += 1
        stamp = STAMP.match(line)
        if stamp:
            result['first'] = result['first'] or stamp.group(1)
            result['last'] = stamp.group(1)
        route = ROUTE.search(line)
        if route:
            result['route_errors'][route.group(1)] += 1
        if SETFAIL.search(line):
            result['set_failure_lines'] += 1
        if START in line:
            result['concentrator_start_lines'] += 1
        match = STACK.search(line)
        if match:
            try:
                raw = json.loads(match.group(1))
            except ValueError:
                continue
            result['stack_configs'].append({k: raw.get(k) for k in (
                'CONCENTRATOR_RAM_TYPE', 'CONCENTRATOR_MIN_TIME',
                'CONCENTRATOR_MAX_TIME', 'CONCENTRATOR_ROUTE_ERROR_THRESHOLD',
                'CONCENTRATOR_DELIVERY_FAILURE_THRESHOLD')})
    result['route_errors'] = dict(sorted(result['route_errors'].items()))
    return result


def report(archive_path):
    grouped = collections.defaultdict(list)
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive:
            if not (member.isfile() and member.name.startswith('private/log/')
                    and member.name.endswith('.log')):
                continue
            session = member.name.split('/')[2]
            with archive.extractfile(member) as source:
                grouped[session].extend(b.decode('utf-8', 'replace') for b in source)
    if not grouped:
        raise ValueError('Archive contains no captured Zigbee2MQTT logs')
    sessions = {name: inspect(lines) for name, lines in sorted(grouped.items())}
    total_mto = sum(v['route_errors'].get('MANY_TO_ONE_ROUTE_FAILURE', 0) for v in sessions.values())
    total_fail = sum(v['set_failure_lines'] for v in sessions.values())
    startup_seen = sum(bool(v['concentrator_start_lines']) for v in sessions.values())
    decision = ('CONCENTRATOR_START_SEEN_BUT_ON_AIR_REPAIR_UNVERIFIED' if startup_seen
                else 'CONCENTRATOR_START_NOT_CAPTURED_DO_NOT_INFER_DISABLED')
    return {'capture_only': True, 'ha_reads': 0, 'ha_mutations': 0,
            'many_to_one_error_lines': total_mto, 'set_failure_text_lines': total_fail,
            'owner_sessions': len(sessions), 'sessions_with_concentrator_start': startup_seen,
            'decision': decision, 'recommendation':
            'Do not add duplicate MTORR refresh or blindly change thresholds. '
            'Use one isolated, automated link-loss/recovery test of the existing concentrator '
            'and NCP broadcast admission; do not alter production network identity.',
            'sessions': sessions}


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Provide exact path to the ONE existing private archive')
    print(json.dumps(report(sys.argv[1]), indent=2, sort_keys=True))
