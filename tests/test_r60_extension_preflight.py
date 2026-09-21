"""R60 extension preflight contract: offline only; does not contact Home Assistant."""
import ast
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy' / 'r60_extension_preflight.py'
spec = importlib.util.spec_from_file_location('r60_extension_preflight', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def normal():
    return dict(owner_count=1, owner_running=True, serial_adapter='ember',
                z2m_package_version='2.14.0', herdsman_version='10.9.1',
                external_extension_loader_present=True, extension_file_preexisting=False,
                owner_started_utc='2026-09-21T18:36:47Z', owner_image='z2m:2.14.0-1',
                captured_utc='2026-09-21T20:25:00Z')


class R60PreflightTests(unittest.TestCase):
    def test_remote_is_valid_python_and_read_only(self):
        ast.parse(mod.REMOTE)
        forbidden = ('mqtt_pub', 'docker restart', 'docker stop', 'docker cp',
                     'save', 'bridge/request', 'configuration.yaml\').write',
                     'serialport', 'ezspGetNeighbor', 'networkmap')
        for value in forbidden:
            self.assertNotIn(value, mod.REMOTE)
        self.assertIn("'docker', 'ps'", mod.REMOTE)
        self.assertIn("'docker','inspect'", mod.REMOTE)

    def test_known_versions_allow_static_preflight_but_never_authorize_deployment(self):
        result = mod.evaluate(normal(), 'a'*64)
        self.assertTrue(result['static_preflight_ok'])
        self.assertFalse(result['deployment_authorized'])
        self.assertGreaterEqual(len(result['not_proven']), 3)

    def test_conflict_and_bad_hash_fail_closed(self):
        state = normal(); state['extension_file_preexisting'] = True
        result = mod.evaluate(state, 'not-a-sha256')
        self.assertFalse(result['static_preflight_ok'])
        self.assertIn('existing_extension_conflict', result['blockers'])
        self.assertIn('extension_hash_invalid', result['blockers'])

    def test_versions_and_owner_count_fail_closed(self):
        for field, value in [('owner_count', 2), ('owner_running', False),
                             ('serial_adapter', 'zstack'), ('z2m_package_version', '2.15.0'),
                             ('herdsman_version', '10.9.2'), ('external_extension_loader_present', False),
                             ('owner_started_utc', None)]:
            with self.subTest(field=field):
                state = normal(); state[field] = value
                self.assertFalse(mod.evaluate(state, 'b'*64)['static_preflight_ok'])

    def test_no_private_identifiers_exposed_in_output(self):
        state = normal(); state['network_key'] = 'secret'; state['ieee'] = 'private'
        result = mod.evaluate(state, 'c'*64)
        self.assertNotIn('network_key', result)
        self.assertNotIn('ieee', result)


if __name__ == '__main__': unittest.main()
