"""Offline-only issue #28 neighbor time-series analysis tests."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import r60_neighbor_series_analyze as s

class SeriesAnalysisTests(unittest.TestCase):
    def samples(self):
        t = datetime(2026, 9, 22, 16, 0, tzinfo=timezone.utc)
        return {'issue':28, 'complete':True, 'observations':[
            {'index':i,'status':'ok','snapshot':{'owner_epoch':'same',
              'captured_utc':(t+timedelta(seconds=60*i)).isoformat(),
              'private_result_path':str(i)}} for i in range(11)]}
    def load(self, snap):
        index=int(snap['private_result_path'])
        ids=list(range(26))
        if index in (1,2,3): ids[0]=26
        if index >= 4: ids[1]=27
        return {'entries':[{'longId':f'{i:016x}', 'outCost':0 if i==0 else 2,'age':1}
            for i in ids]}
    def test_departure_return_and_identity_redaction(self):
        data=s.analyze(self.samples(),self.load)
        self.assertEqual(data['sample_count'],11)
        self.assertEqual(data['unique_direct_neighbors_seen'],28)
        self.assertEqual(data['observed_departure_events'],3)
        self.assertEqual(data['unique_returned_neighbor_count'],1)
        self.assertEqual(data['departed_previous_outcost_unknown'],1)
        self.assertNotIn('0000000000000000',json.dumps(data))
    def test_incomplete_capture_rejected(self):
        row=self.samples(); row['complete']=False
        with self.assertRaisesRegex(ValueError,'incomplete'):s.analyze(row,self.load)
    def test_owner_change_rejected(self):
        row=self.samples();row['observations'][5]['snapshot']['owner_epoch']='other'
        with self.assertRaisesRegex(ValueError,'changed_owner'):s.analyze(row,self.load)
    def test_spacing_gap_rejected(self):
        row=self.samples();row['observations'][5]['snapshot']['captured_utc']='2026-09-22T16:15:00+00:00'
        with self.assertRaisesRegex(ValueError,'noncomparable'):s.analyze(row,self.load)
    def test_duplicate_identity_rejected(self):
        def duplicate(snap):
            x=self.load(snap);x['entries'][0]['longId']=x['entries'][1]['longId'];return x
        with self.assertRaisesRegex(ValueError,'duplicate'):s.analyze(self.samples(),duplicate)

if __name__=='__main__': unittest.main()
