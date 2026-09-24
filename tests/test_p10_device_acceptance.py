"""Synthetic acceptance tests; identifiers in this file are fake."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import p10_device_acceptance as subject


class AcceptanceTests(unittest.TestCase):
    def sample(self):
        rows = [{'type': 'Coordinator', 'ieeeAddr': '0x0000000000000001'},
                {'type': 'Router', 'ieeeAddr': '0x0000000000000002', 'lastSeen': 100000},
                {'type': 'EndDevice', 'ieeeAddr': '0x0000000000000003', 'lastSeen': 100000},
                {'type': 'Group', 'groupID': 17}]
        return subject.parse_database('\n'.join(json.dumps(r) for r in rows).encode())

    def test_old_database_entries_are_not_counted_as_recovered(self):
        before = self.sample()
        new = self.sample()
        new['devices']['0x0000000000000002']['last_seen_ms'] = 200000
        result, details = subject.compare({'baseline': before}, new,
                                           datetime.fromtimestamp(150, timezone.utc))
        self.assertEqual(result['expected_devices'], 2)
        self.assertEqual(result['inbound_seen_since_cutover'], 1)
        self.assertEqual(result['no_new_inbound_report'], 1)
        self.assertFalse(result['outbound_command_delivery_tested'])
        self.assertEqual(len(details['no_report']), 1)

    def test_missing_router_group_and_role_change_reported(self):
        old = self.sample()
        post = self.sample()
        del post['devices']['0x0000000000000002']
        post['devices']['0x0000000000000003']['role'] = 'Router'
        post['group_ids'] = []
        summary, details = subject.compare({'baseline': old}, post,
                                            datetime.fromtimestamp(150, timezone.utc))
        self.assertEqual(summary['database_records_missing'], 1)
        self.assertEqual(summary['role_changed'], 1)
        self.assertEqual(summary['groups_missing'], 1)
        self.assertEqual(len(details['missing']), 1)

    def test_refuse_duplicate_device_or_group(self):
        valid = b'{"type":"Coordinator","ieeeAddr":"0x0000000000000001"}'
        with self.assertRaises(ValueError):
            subject.parse_database(valid + b'\n' + valid)
        group = b'{"type":"Group","groupID":17}'
        with self.assertRaises(ValueError):
            subject.parse_database(valid + b'\n' + group + b'\n' + group)

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            subject.compare({'baseline': self.sample()}, self.sample(), datetime(2026,9,24))


if __name__ == '__main__':
    unittest.main()
