"""Offline verification of exact-ZCL cohorts and A/B decisions; no HA use."""
import importlib.util,sys,unittest
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]/'deploy';sys.path.insert(0,str(root))
import r60_verified_reads as zcl
import r60_placement_experiment as ab
import r60_rf_window as rf
SYNTHETIC=['HallRouterOne','KitchenRouterOne','LivingRoomRouterOne','WorkroomRouterOne','BathroomRouterOne','HallRouterTwo','KitchenRouterTwo','LivingRoomRouterTwo','WorkroomRouterTwo','KitchenRouterThree','LivingRoomRouterThree']
class EndToEndTests(unittest.TestCase):
 def sample(self,verified=3):
  return {'repeats':3,'names':SYNTHETIC,'results':[
   {'name':name,'round':rnd,'status':'zcl_verified' if rnd<verified else 'zcl_read_failed',
    'latency_ms':100,'network_address':123+rnd*0} for rnd in range(3) for name in SYNTHETIC]}
 def metrics(self,failed,neighbor):
  return {'mac_failure_fraction':failed,'mac_failure_per_min':failed*100,
   'neighbor_changes_per_min':neighbor,'cca_failures_per_min':5,'mac_retries_per_min':20,'mac_frames':400}
 def test_verified_result_only_when_real_response(self):
  x=zcl.summarize(self.sample(2),required=SYNTHETIC);self.assertEqual(x['verified'],22)
  self.assertTrue(all(d['network_address']==123 for d in x['devices']))
  x=self.sample(3);x['results'][0]['status']='fresh_state'
  result=zcl.summarize(x,required=SYNTHETIC)
  self.assertEqual(result['verified'],32)
  self.assertEqual(result['devices'][0]['statuses']['fresh_state'],1)
 def test_changed_round_rejected(self):
  x=self.sample();x['results'][0]['round']=2
  with self.assertRaisesRegex(ValueError,'nonmatching'):zcl.summarize(x,required=SYNTHETIC)
 def test_critical_device_regression_overrides_rf_improvement(self):
  good=zcl.summarize(self.sample(3),required=SYNTHETIC);bad=zcl.summarize(self.sample(2),required=SYNTHETIC)
  before={'metrics':self.metrics(.15,10),'zcl':good}
  after={'metrics':self.metrics(.03,2),'zcl':bad}
  result=ab.summarize_delta(before,after)
  self.assertIn('regression',result['verdict']);self.assertEqual(len(result['regressed_devices']),11)
 def test_improvement_with_identical_device_outcomes(self):
  good=zcl.summarize(self.sample(3),required=SYNTHETIC)
  out=ab.summarize_delta({'metrics':self.metrics(.15,10),'zcl':good},
                         {'metrics':self.metrics(.03,2),'zcl':good})
  self.assertIn('short-window RF improvement',out['verdict'])
 def test_traffic_imbalance_is_inconclusive(self):
  g=zcl.summarize(self.sample(3),required=SYNTHETIC);a=self.metrics(.15,10);b=self.metrics(.03,2);b['mac_frames']=2000
  self.assertIn('inconclusive',ab.summarize_delta({'metrics':a,'zcl':g},{'metrics':b,'zcl':g})['verdict'])
 def test_route_chain_is_cached_and_detects_cycle(self):
  row={'source_route_entries':[{'index':0,'destination':12,'closerIndex':1},
          {'index':1,'destination':10,'closerIndex':255}], 'entries':[{'shortId':10}]}
  self.assertEqual(rf.route_firsthop(row,12)['firsthop_short'],10)
  row['source_route_entries'][1]['closerIndex']=0
  self.assertEqual(rf.route_firsthop(row,12)['status'],'cached_route_cycle')
 def test_rejected_B_is_preserved_and_valid_retry_selected(self):
  import json,tempfile
  with tempfile.TemporaryDirectory() as directory:
   original=Path(directory)/'after.json'; retry=Path(directory)/'after_retry1.json'
   invalid={'valid':False,'phase':'after','reason':'ncp_counter_reset_or_wrap'}
   original.write_text(json.dumps(invalid),encoding='utf8')
   def location(stage):return {'after':original,'after_retry1':retry}[stage]
   with patch.object(ab,'file',side_effect=location):
    with self.assertRaisesRegex(RuntimeError,'no_valid_after_attempt'):ab.selected_after()
    retry.write_text(json.dumps({'valid':True,'phase':'after_retry1'}),encoding='utf8')
    self.assertEqual(ab.selected_after()['phase'],'after_retry1')
    self.assertEqual(json.loads(original.read_text(encoding='utf8')),invalid)
if __name__=='__main__':unittest.main()
