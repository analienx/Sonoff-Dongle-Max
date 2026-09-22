"""Offline fault cases; never contact HA."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'deploy'/'r60_rf_window.py'
s=importlib.util.spec_from_file_location('r60_rf_window',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class RFTests(unittest.TestCase):
 def test_membership_and_quality(self):
  with tempfile.TemporaryDirectory(prefix='sonoff-private-') as d:
   root=Path(d)/'sonoff-private';root.mkdir()
   def mk(tag,entries):
    path=root/(tag+'.json');path.write_text(json.dumps({'status':'ok','extension_absent_after':True,'snapshot':{'entries':entries,'count':len(entries),'source_route_filled':79}}));return {'private_result_path':str(path)}
   a=mk('a',[{'longId':'a','averageLqi':100,'outCost':1},{'longId':'b','averageLqi':90,'outCost':1}]);b=mk('b',[{'longId':'a','averageLqi':110,'outCost':1},{'longId':'c','averageLqi':80,'outCost':0}]);x=m.compare(a,b)
   self.assertEqual((x['distinct_departed'],x['distinct_entered'],x['stable_neighbors']), (1,1,1));self.assertEqual(x['outbound_cost_zero_after'],1)
 def test_missing_path_never_claims_first_hop(self):
  x=m.fingerprint({'results':[{'name':'KitchenSocketX','status':'no_verified_response'}]})
  self.assertIn('no first-hop assertion',x['path_attribution']);self.assertEqual(x['verified_zcl'],0)
if __name__=='__main__':unittest.main()
