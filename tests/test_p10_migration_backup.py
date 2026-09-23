"""Synthetic-only tests: never put household backup data in Git."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import p10_migration_backup as subject


def sample(db_records=3, backup_records=0):
    db = '\n'.join(json.dumps({'type': role, 'ieeeAddr': f'0x{i:016x}'})
                   for i, role in enumerate(['Coordinator', 'Router', 'EndDevice'][:db_records]))
    stored = [{'ieee_address': f'0x{i:016x}', 'link_key': {'key': 'fake'}}
              for i in range(1, backup_records + 1)]
    return {'database.db': db.encode(), 'configuration.yaml': b'permit_join: false',
            'coordinator_backup.json': json.dumps({'devices': stored, 'stack_specific': {'ezsp': {}}, 'coordinator_ieee':'fake', 'pan_id':1, 'extended_pan_id':'fake', 'channel':11, 'network_key':{'key':'fake'}}).encode()}


class BackupTests(unittest.TestCase):
    def test_empty_coordinator_records_block(self):
        result = subject.preflight(sample())
        self.assertEqual(result['status'], 'PREFLIGHT_REVIEW_REQUIRED')
        self.assertEqual(result['database']['roles']['Router'], 1)
        self.assertEqual(result['coordinator_backup_records'], 0)

    def test_complete_records_only_count_match(self):
        result = subject.preflight(sample(3, 2))
        self.assertEqual(result['status'], 'RECORD_COUNTS_MATCH_ONLY')
        self.assertFalse(result['migration_authorized'])

    def test_missing_backup_file_blocked(self):
        data = sample()
        del data['coordinator_backup.json']
        self.assertEqual(subject.preflight(data)['status'], 'BLOCKED')

    def test_duplicate_database_identity_rejected(self):
        data = sample()
        first = data['database.db'].splitlines()[0]
        data['database.db'] += b'\n' + first
        with self.assertRaises(ValueError):
            subject.preflight(data)

    def test_archive_created_even_if_migration_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'source'
            root.mkdir()
            for name, payload in sample().items():
                (root / name).write_bytes(payload)
            dest = Path(temp) / 'private' / 'snapshot.zip'
            report = subject.archive(root, dest)
            self.assertTrue(dest.is_file())
            self.assertEqual(report['status'], 'PREFLIGHT_REVIEW_REQUIRED')
            self.assertIn('coordinator_backup.json', report['file_hashes'])
            with self.assertRaises(FileExistsError):
                subject.archive(root, dest)


if __name__ == '__main__':
    unittest.main()
