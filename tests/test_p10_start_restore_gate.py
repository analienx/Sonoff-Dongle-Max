"""Backup-driven Ember→Z-Stack restoration occurs at first Z2M start, not before."""
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import p10_ha_apply as apply
import p10_ha_start as start

class StartupRestoreGate(TestCase):
    def test_target_config_accepts_preserved_backup_not_fake_restored_state(self):
        approvals=['source-isolated','source-backup-preserved',
                   'effective-ieee-verified','exclusive-radio-client']
        with patch.object(apply,'live_plan',return_value={'safe_to_apply_config':False}):
            with self.assertRaisesRegex(RuntimeError,'differs'):
                apply.apply(Path('fake'),'target',apply.PHRASES['target'],approvals)
            with self.assertRaisesRegex(ValueError,'attestations'):
                apply.apply(Path('fake'),'target',apply.PHRASES['target'],
                    [x for x in approvals if x!='source-backup-preserved'])

    def test_start_gate_requires_backup_but_not_impossible_prestart_restore(self):
        required=start.NEEDED['target']
        self.assertIn('source-backup-preserved',required)
        self.assertNotIn('existing-network-restored',required)
        with patch.object(start,'prestart',return_value={'addon_stopped_and_both_config_layers_match':False}):
            with self.assertRaisesRegex(RuntimeError,'does not match'):
                start.start(Path('fake'),'target',start.START_PHRASES['target'],sorted(required))
