"""Private device-by-device migration baseline and post-cutover lastSeen comparison.

Records retained in database.db do NOT mean devices recovered. A recent lastSeen
only proves an observed inbound report, not routing, commands or group delivery.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from p10_cutover_prepare import private_target

ROLES = ('Coordinator', 'Router', 'EndDevice')


def parse_database(data: bytes) -> dict:
    records, groups = {}, set()
    for line in data.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get('type') == 'Group':
            group_id = item.get('groupID')
            if type(group_id) is not int or group_id in groups:
                raise ValueError('Duplicate or invalid Zigbee group')
            groups.add(group_id)
            continue
        ieee = item.get('ieeeAddr')
        role = item.get('type')
        if role not in ROLES or not isinstance(ieee, str) or ieee.lower() in records:
            raise ValueError('Duplicate or invalid Zigbee device')
        records[ieee.lower()] = {'role': role, 'last_seen_ms': item.get('lastSeen')}
    if sum(x['role']=='Coordinator' for x in records.values()) != 1:
        raise ValueError('Expected exactly one coordinator')
    return {'devices': records, 'group_ids': sorted(groups)}


def baseline(snapshot: Path, output: Path) -> dict:
    source, dest = private_target(snapshot), private_target(output)
    db = source / 'database.db'
    observed = parse_database(db.read_bytes())
    record = {'captured_at_utc': datetime.now(timezone.utc).isoformat(),
              'baseline': observed, 'source_database_file': db.name}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('x', encoding='utf-8') as out:
        json.dump(record, out, indent=2, sort_keys=True)
    return {'status': 'BASELINE_CREATED', 'device_count': len(observed['devices']),
            'group_count': len(observed['group_ids']), 'contains_live_device_checks': False}


def compare(record: dict, post: dict, after: datetime) -> tuple[dict, dict]:
    if after.tzinfo is None:
        raise ValueError('Cutover timestamp must contain an explicit timezone')
    threshold = int(after.timestamp() * 1000)
    before = record['baseline']['devices']
    current = post['devices']
    ordinary = {ieee: item for ieee, item in before.items() if item['role'] != 'Coordinator'}
    missing = sorted(set(ordinary) - set(current))
    reclassified = sorted(ieee for ieee in ordinary if ieee in current and ordinary[ieee]['role'] != current[ieee]['role'])
    seen = sorted(ieee for ieee in ordinary if ieee in current and
                  type(current[ieee]['last_seen_ms']) is int and current[ieee]['last_seen_ms'] >= threshold)
    unseen = sorted(set(ordinary) - set(seen) - set(missing))
    groups_lost = sorted(set(record['baseline']['group_ids']) - set(post['group_ids']))
    summary = {'status': 'OBSERVATION_ONLY_NOT_ROUTING_PROOF',
               'expected_devices': len(ordinary), 'inbound_seen_since_cutover': len(seen),
               'no_new_inbound_report': len(unseen), 'database_records_missing': len(missing),
               'role_changed': len(reclassified), 'groups_missing': len(groups_lost),
               'routers_expected': sum(x['role']=='Router' for x in ordinary.values()),
               'routers_seen': sum(ordinary[x]['role']=='Router' for x in seen),
               'end_devices_expected': sum(x['role']=='EndDevice' for x in ordinary.values()),
               'end_devices_seen': sum(ordinary[x]['role']=='EndDevice' for x in seen),
               'outbound_command_delivery_tested': False, 'groupcast_tested': False,
               'source_route_capacity_proven': False}
    details = {'missing': missing, 'reclassified': reclassified, 'no_report': unseen,
               'reported': seen, 'groups_lost': groups_lost}
    return summary, details


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    tasks = p.add_subparsers(dest='action', required=True)
    a = tasks.add_parser('baseline')
    a.add_argument('--snapshot', type=Path, required=True)
    a.add_argument('--out', type=Path, required=True)
    b = tasks.add_parser('compare')
    b.add_argument('--baseline', type=Path, required=True)
    b.add_argument('--post-snapshot', type=Path, required=True)
    b.add_argument('--cutover-utc', required=True)
    b.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.action == 'baseline':
            result = baseline(args.snapshot, args.out)
        else:
            old = json.loads(private_target(args.baseline).read_text(encoding='utf-8'))
            post = parse_database((private_target(args.post_snapshot) / 'database.db').read_bytes())
            since = datetime.fromisoformat(args.cutover_utc.replace('Z', '+00:00'))
            result, details = compare(old, post, since)
            dest = private_target(args.out)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open('x', encoding='utf-8') as out:
                json.dump({'summary': result, 'private_device_details': details}, out, indent=2)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('P10_ACCEPTANCE_ERROR: ' + str(exc)[:120], file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
