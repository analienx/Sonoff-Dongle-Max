"""Synthetic orchestration tests: no HA mutations, keys or real identifiers."""
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import p10_usb_handoff as handoff

class HandoffTests(TestCase):
    @patch.object(handoff, 'prepare')
    def test_no_approval_never_stops_z2m(self, prepare):
        with self.assertRaisesRegex(ValueError, 'approval'):
            handoff.begin(Path('hot.zip'), Path('cold.zip'), Path('stage'), 'WRONG')
        prepare.assert_not_called()

    @patch.object(handoff, 'source_hash', return_value='a'*64)
    @patch.object(handoff, 'source_state', return_value={'state':'started','source_yaml_matches':True})
    @patch.object(handoff, 'private_target', side_effect=lambda p:p)
    def test_dryrun_preserves_service(self, targets, state, digest):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as path:
            p=Path(path)
            report=handoff.prepare(p/'hot.zip',p/'cold.zip',p/'stage')
        self.assertEqual(report['status'],'DRY_RUN_SOURCE_MATCHES')
        self.assertFalse(report['sonoff_disconnect_authorized'])
        state.assert_called_once()

    @patch.object(handoff, 'prepare')
    @patch.object(handoff, 'source_hash', return_value='b'*64)
    @patch.object(handoff, 'freeze')
    @patch.object(handoff, 'verify', return_value={'integrity_pass':True,'cold_consistent':True,'application_file_count':255})
    @patch.object(handoff, 'stage_source', return_value={'bundle_cold':True,'bundle_integrity_pass':True})
    @patch.object(handoff, 'private_target', side_effect=lambda p:p)
    @patch.object(handoff, 'load_ha')
    @patch.object(handoff, 'addon_info', return_value={'state':'stopped','boot':'manual','watchdog':False})
    def test_success_only_after_cold_and_stage_and_stopped(self,info,connection,priv,stage,verify,freeze,hashes,prepare):
        result=handoff.begin(Path('hot.zip'),Path('cold.zip'),Path('stage'),handoff.APPROVAL)
        self.assertEqual(result['status'],'READY_TO_DISCONNECT_SONOFF')
        self.assertTrue(result['cold_backup_verified'])
        self.assertFalse(result['physical_sonoff_isolation_performed'])
        freeze.assert_called_once_with(Path('cold.zip'),'b'*64,handoff.FREEZE_APPROVAL)
        stage.assert_called_once()
        connection.return_value.close.assert_called_once()

    @patch.object(handoff, 'prepare')
    @patch.object(handoff, 'source_hash', return_value='c'*64)
    @patch.object(handoff, 'freeze')
    @patch.object(handoff, 'verify', return_value={'integrity_pass':False,'cold_consistent':False})
    @patch.object(handoff, 'stage_source')
    @patch.object(handoff, 'private_target', side_effect=lambda p:p)
    def test_invalid_cold_archive_never_authorizes_unplug(self,priv,stage,verify,freeze,hashes,prepare):
        with self.assertRaisesRegex(RuntimeError, 'cold backup verification FAILED'):
            handoff.begin(Path('hot.zip'),Path('cold.zip'),Path('stage'),handoff.APPROVAL)
        stage.assert_not_called()
