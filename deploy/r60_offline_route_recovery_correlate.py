#!/usr/bin/env python3
"""Offline-only: sanitized correlation of existing private one-pass Z2M logs.

Reads archive on authorized laptop, prints aggregates only; no HA access or writes.
"""
import collections
import datetime as dt
import json
import pathlib
import re
import tarfile

root = pathlib.Path(r'C:\Workspace\.analienx\sonoff-private')
archives = list(root.glob('r60_ha_one_pass_*.tar.gz'))
if len(archives) != 1:
    raise SystemExit('Expected exactly one existing private archive')
errors = []
commands = []
received = collections.Counter()
other = collections.Counter()
sessions = collections.Counter()
route_record_lines = []
pattern = re.compile(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]')
error_re = re.compile(r'ROUTE_ERROR_([A-Z_]+) for ["\']?(\d+)')
recv_re = re.compile(r'Received Zigbee message from ["\']([^"\']+)')
with tarfile.open(archives[0], 'r:gz') as tar:
    for member in tar.getmembers():
        if not member.isfile() or not member.name.endswith('.log') or '/log/' not in member.name:
            continue
        session = member.name.rsplit('/', 2)[-2]
        raw = tar.extractfile(member)
        assert raw is not None
        for line in raw:
            text = line.decode('utf-8', 'replace')
            mt = pattern.match(text)
            if not mt:
                continue
            t = dt.datetime.strptime(mt.group(1), '%Y-%m-%d %H:%M:%S')
            sessions[session] += 1
            e = error_re.search(text)
            if e:
                errors.append((t, session, e.group(1), e.group(2)))
            if "Failed to publish 'set'" in text or ("Publish 'set'" in text and 'failed' in text.lower()):
                dev = re.search(r"to '([^']+)'", text)
                commands.append((t, session, 'set', dev.group(1) if dev else None))
            elif 'Failed to ping' in text and 'Timed out' in text:
                commands.append((t, session, 'ping', None))
            recv = recv_re.search(text)
            if recv:
                received[recv.group(1)] += 1
            lower = text.lower()
            for key, term in [('route_record', 'route record'), ('source_routes', 'sourceroute'),
                              ('mtorr', 'many-to-one route request'), ('discover', 'route discovery'),
                              ('busy', 'slstatus.busy'), ('packet_fail', 'allocate_packet_buffer_failure'),
                              ('broadcast_full', 'broadcast_table_full'), ('aps_failure', 'aps_data_tx_unicast_failed')]:
                if term in lower:
                    other[key] += 1
                    if key in ('route_record','source_routes','mtorr','discover') and len(route_record_lines)<10:
                        route_record_lines.append((session, t.isoformat(), key))
intervals = collections.Counter()
for t, s, kind, dev in commands:
    near = [e for e in errors if e[1] == s and abs((e[0]-t).total_seconds())<=10]
    intervals[(kind, bool(near))] += 1
per_session = {}
for s in sessions:
    session_errors = collections.Counter(e[2] for e in errors if e[1] == s)
    failed_set = sum(c[1]==s and c[2]=='set' for c in commands)
    per_session[s] = {'route_errors':dict(session_errors),'failed_set_log_lines':failed_set,
                      'log_lines': sessions[s]}
print(json.dumps({'archive_files':len(sessions),'error_type_counts':dict(collections.Counter(e[2] for e in errors)),
                  'command_failure_counts':dict(collections.Counter(c[2] for c in commands)),
                  'command_errors_within_10sec':{f'{k[0]}_near_error_{k[1]}':v for k,v in intervals.items()},
                  'debug_receive_top8':received.most_common(8),'recovery_instrumentation_keywords':dict(other),
                  'recovery_keyword_samples_no_identifiers':route_record_lines,
                  'sessions':per_session}, sort_keys=True))
