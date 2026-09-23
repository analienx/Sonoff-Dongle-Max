"""Offline-only regression tests for issue #28 bounded neighbor time series."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import r60_neighbor_ten_min as series

class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(series, 'PRIVATE', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.elapsed = 0
        self.samples = 0

    def clock(self): return self.elapsed
    def sleep(self, seconds): self.elapsed += seconds
    def sampler(self):
        number = self.samples
        self.samples += 1
        return {'count': 26, 'owner_epoch': 'same-owner',
            'captured_utc': '2026-09-22T16:00:00+00:00',
            'private_result_path': str(number)}
    def loader(self, snapshot):
        n = int(snapshot['private_result_path'])
        ids = list(range(26))
        if n: ids[0] = 26
        return {'entries': [{'longId': f'{ident:016x}', 'age': 1, 'outCost': 0 if ident == 0 else 2}
            for ident in ids]}

    def test_eleven_samples_one_minute_apart_and_no_raw_ids_in_summary(self):
        with patch.object(series, 'load_private', self.loader):
            path, result = series.capture(sampler=self.sampler, sleeper=self.sleep, clock=self.clock)
        self.assertTrue(result['complete'])
        self.assertEqual((self.samples, self.elapsed), (11, 600))
        self.assertEqual(result['summary']['observed_departs'], 1)
        self.assertEqual(result['summary']['unknown_outcost_before_departure'], 1)
        self.assertFalse((self.root/'r60_neighbor_ten_min_active.lock').exists())
        self.assertTrue(path.exists())
        self.assertNotIn('0000000000000000', json.dumps(result['summary']))

    def test_failed_sample_preserves_partial_evidence_and_removes_lock(self):
        def fail_third():
            if self.samples == 2: raise RuntimeError('mock_incomplete_gate')
            return self.sampler()
        with patch.object(series, 'load_private', self.loader):
            path, result = series.capture(sampler=fail_third, sleeper=self.sleep, clock=self.clock)
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['observations']), 2)
        self.assertIn('mock_incomplete_gate', result['reason'])
        self.assertTrue(path.exists())
        self.assertFalse((self.root/'r60_neighbor_ten_min_active.lock').exists())

    def test_owner_change_aborts_without_substituting_samples(self):
        def changed_owner():
            item = self.sampler()
            if self.samples == 2: item['owner_epoch'] = 'new-owner'
            return item
        with patch.object(series, 'load_private', self.loader):
            _, result = series.capture(sampler=changed_owner, sleeper=self.sleep, clock=self.clock)
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['observations']), 1)
        self.assertIn('owner_epoch_changed', result['reason'])

    def test_invalid_profile_rejected_before_any_probe(self):
        with self.assertRaisesRegex(ValueError, 'only_reviewed'):
            series.capture(seconds=700, sampler=self.sampler, sleeper=self.sleep, clock=self.clock)
        self.assertEqual(self.samples, 0)

    def test_existing_lock_blocks_concurrent_series(self):
        self.root.joinpath('r60_neighbor_ten_min_active.lock').write_text('running')
        with self.assertRaises(FileExistsError):
            series.capture(sampler=self.sampler, sleeper=self.sleep, clock=self.clock)
        self.assertEqual(self.samples, 0)

if __name__ == '__main__': unittest.main()
