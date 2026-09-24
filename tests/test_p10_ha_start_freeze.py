"""Operator gate tests; no live HA mutation or household device data."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import p10_outage_freeze as freeze
import p10_ha_start as start

class FreezeTests(unittest.TestCase):
    def test_missing_approval_never_calls_ha(self):
        with patch.object(freeze,'load_ha',side_effect=AssertionError('no HA call')):
            with self.assertRaisesRegex(ValueError,'approval phrase'):
                freeze.freeze(Path('fake.zip'),'a'*64,'wrong')

    def test_bad_source_hash_never_calls_ha(self):
        with patch.object(freeze,'load_ha',side_effect=AssertionError('no HA call')):
            with self.assertRaisesRegex(ValueError,'lowercase hex'):
                freeze.source_state('not-a-sha')

class StartTests(unittest.TestCase):
    def test_start_refuses_wrong_phase_approval_without_ha(self):
        with patch.object(start,'prestart',side_effect=AssertionError('no plan')):
            with self.assertRaisesRegex(ValueError,'approval'):
                start.start(Path('fake'),'target','wrong',[])

    def test_start_requires_isolation_and_radio_identity(self):
        with patch.object(start,'prestart',side_effect=AssertionError('no plan')):
            with self.assertRaisesRegex(ValueError,'attestations'):
                start.start(Path('fake'),'target',start.START_PHRASES['target'],['source-isolated'])
            with self.assertRaisesRegex(ValueError,'attestations'):
                start.start(Path('fake'),'rollback',start.START_PHRASES['rollback'],['target-isolated'])

    def test_incorrect_two_layer_config_prevents_start(self):
        with patch.object(start,'prestart',return_value={'addon_stopped_and_both_config_layers_match':False}),\
             patch.object(start,'load_ha',side_effect=AssertionError('should not connect')):
            with self.assertRaisesRegex(RuntimeError,'does not match'):
                start.start(Path('fake'),'rollback',start.START_PHRASES['rollback'],
                            ['target-isolated','original-sonoff-state-preserved'])

if __name__=='__main__': unittest.main()
