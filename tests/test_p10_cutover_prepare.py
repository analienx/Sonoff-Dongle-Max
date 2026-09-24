"""Synthetic migration preparation fixtures; never copy household secrets into Git."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import p10_cutover_prepare as prep
import p10_config_stage as staged
import p10_target_endpoint as endpoint


def fixture():
    records = [{'type': 'Coordinator', 'ieeeAddr': '0x0000000000000001'},
               {'type': 'Router', 'ieeeAddr': '0x0000000000000002'},
               {'type': 'EndDevice', 'ieeeAddr': '0x0000000000000003'},
               {'type': 'Group', 'groupID': 7, 'members': []}]
    config = {'channel': 11, 'serial': {'adapter': 'ember', 'port': '/dev/serial/by-id/fake',
              'baudrate': 115200, 'rtscts': False},
              'mqtt': {'password': 'DUMMY_PRIVATE_TEST_ONLY'}, 'groups': {7: {'friendly_name': 'Test'}}}
    backup = {'devices': [], 'metadata': {'format': 'zigpy/open-coordinator-backup'},
              'stack_specific': {'ezsp': {}}, 'coordinator_ieee': '0011223344556677',
              'pan_id': 10, 'extended_pan_id': '0011223344556677', 'channel': 11,
              'network_key': {'key': 'DUMMY_NONREAL_TEST_ONLY', 'frame_counter': 20000}}
    return {'configuration.yaml': yaml.safe_dump(config).encode(),
            'coordinator_backup.json': json.dumps(backup).encode(),
            'database.db': ('\n'.join(json.dumps(row) for row in records)).encode()}


class PreparationTests(unittest.TestCase):
    def test_live_format_devices_and_groups(self):
        doc = prep.inspect(fixture())
        self.assertEqual(doc['z2m_database']['records'], 3)
        self.assertEqual(doc['z2m_database']['groups'], 1)
        self.assertTrue(doc['ember_empty_device_records_can_be_expected'])
        self.assertEqual(doc['channel'], 11)
        self.assertFalse(doc['migration_authorized'])
        self.assertNotIn('DUMMY_PRIVATE', json.dumps(doc))

    def test_wrong_source_or_missing_security_counter_refused(self):
        blobs = fixture()
        conf = yaml.safe_load(blobs['configuration.yaml'])
        conf['serial']['adapter'] = 'zstack'
        with self.assertRaises(ValueError):
            prep.inspect({**blobs, 'configuration.yaml': yaml.safe_dump(conf).encode()})
        backup = json.loads(blobs['coordinator_backup.json'])
        del backup['network_key']['frame_counter']
        with self.assertRaises(ValueError):
            prep.inspect({**blobs, 'coordinator_backup.json': json.dumps(backup).encode()})

    def test_target_endpoint_validation(self):
        endpoint.check_address('192.168.50.2', 7638)
        for host in ('127.0.0.1', '8.8.8.8', '::1'):
            with self.assertRaises(ValueError):
                endpoint.check_address(host, 7638)
        with self.assertRaises(ValueError):
            endpoint.check_address('192.168.50.2', 0)

    def test_render_changes_only_serial_keeps_credentials(self):
        source = yaml.safe_load(fixture()['configuration.yaml'])
        rendered = yaml.safe_load(staged.render(fixture()['configuration.yaml'], '192.168.50.2', 7638))
        self.assertEqual(rendered['serial']['port'], 'tcp://192.168.50.2:7638')
        self.assertEqual(rendered['serial']['adapter'], 'zstack')
        self.assertEqual(rendered['mqtt'], source['mqtt'])
        self.assertEqual(rendered['groups'], source['groups'])
        self.assertEqual(rendered['channel'], 11)

    def test_staged_rollback_exact_and_target_requires_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            source = private / 'source'
            source.mkdir(parents=True)
            blobs = fixture()
            for name, data in blobs.items():
                (source / name).write_bytes(data)
            (source / 'manifest.private.json').write_text(json.dumps({
                'captured_files_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in blobs.items()}}))
            with patch.object(prep, 'PRIVATE_ROOT', private.resolve()):
                output = private / 'rollback_only'
                report = staged.stage(source, output, 'edbb94f6', None, 7638)
                self.assertEqual((output / 'rollback_configuration.yaml').read_bytes(), blobs['configuration.yaml'])
                self.assertFalse((output / 'target_configuration.yaml').exists())
                self.assertFalse(report['production_changed'])
                with patch.object(staged, 'verify_target', return_value={'znp_radio_verified': True}):
                    output2 = private / 'target_stage'
                    verified = staged.stage(source, output2, 'edbb94f6', '192.168.50.2', 7638)
                    self.assertTrue(verified['target_znp_verified_from_ha'])
                    self.assertEqual(yaml.safe_load((output2 / 'target_configuration.yaml').read_bytes())['serial']['adapter'], 'zstack')
                (source / 'database.db').write_bytes(blobs['database.db'] + b'\n{"type":"Group","groupID":9,"members":[]}')
                with self.assertRaises(RuntimeError):
                    staged.stage(source, private / 'tampered', 'edbb94f6', None, 7638)


if __name__ == '__main__':
    unittest.main()
