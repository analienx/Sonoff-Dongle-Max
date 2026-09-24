"""Native-backup helper tests use fake Supervisor results; no SSH/HA writes."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import p10_native_ha_backup as subject


class NativeBackupTests(unittest.TestCase):
    def test_summary_checks_z2m_app_and_full_backup(self):
        item = {'name': 'precutover', 'slug': 'abc', 'type': 'full', 'size_bytes': 1,
                'content': {'addons': [subject.Z2M_ADDON], 'homeassistant': True}}
        result = subject.summarize(item)
        self.assertTrue(result['zigbee2mqtt_addon_included'])
        self.assertTrue(result['homeassistant_included'])
        self.assertFalse(result['coordinator_cross_stack_migration_proven'])

    def test_existing_backup_does_not_start_duplicate(self):
        item = {'name': 'precutover', 'slug': 'abc', 'type': 'full',
                'content': {'addons': [subject.Z2M_ADDON], 'homeassistant': True}}
        with patch.object(subject, 'query', return_value={'backups': [item]}) as query:
            found = subject.perform(object(), 'precutover')
        self.assertTrue(found['already_existed'])
        query.assert_called_once()

    def test_active_backup_blocks_second_creation(self):
        with patch.object(subject, 'query', side_effect=[{'backups': []},
                     {'jobs': [{'name': 'backup_manager_full_backup', 'done': False}]}]):
            with self.assertRaises(RuntimeError):
                subject.perform(object(), 'precutover')
