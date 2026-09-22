import importlib.util
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / 'deploy' / 'r60_isolated_recovery_gate.py'
spec = importlib.util.spec_from_file_location('r60_isolated_recovery_gate', FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def trace(*events):
    return [{'t': i * 10, 'event': name} for i, name in enumerate(events)]


class RecoveryGateTests(unittest.TestCase):
    def test_valid_isolated_recovery_trace(self):
        self.assertEqual(module.evaluate(trace('isolated', 'alternate_path',
                                              'link_lost', 'mtorr_on_air',
                                              'recovered_command')), 'ISOLATED_RECOVERY_PASS')

    def test_startup_log_is_not_on_air_proof(self):
        self.assertEqual(module.evaluate(trace('isolated', 'alternate_path',
                                              'link_lost', 'concentrator_started',
                                              'recovered_command')), 'NO_ON_AIR_REFRESH_EVIDENCE')

    def test_broadcast_busy_blocks_a_pass(self):
        self.assertEqual(module.evaluate(trace('isolated', 'alternate_path',
                                              'link_lost', 'broadcast_busy',
                                              'mtorr_on_air', 'recovered_command')),
                         'NCP_BROADCAST_ADMISSION_FAILURE')

    def test_restart_or_network_identity_change_blocks_pass(self):
        for failure in ('owner_reset', 'identity_changed'):
            with self.subTest(failure=failure):
                self.assertEqual(module.evaluate(trace('isolated', 'alternate_path',
                                                       'link_lost', failure, 'mtorr_on_air',
                                                       'recovered_command')), 'HARD_FAILURE')

    def test_no_alternative_or_no_repair_never_passes(self):
        self.assertEqual(module.evaluate(trace('isolated', 'link_lost',
                                              'mtorr_on_air', 'recovered_command')),
                         'NO_ISOLATED_ALTERNATE_PATH')
        self.assertEqual(module.evaluate(trace('isolated', 'alternate_path',
                                              'link_lost', 'mtorr_on_air')),
                         'NO_OBSERVED_RECOVERY')

    def test_later_failed_command_blocks_pass(self):
        self.assertEqual(module.evaluate(trace('isolated', 'alternate_path',
                                              'link_lost', 'mtorr_on_air',
                                              'recovered_command', 'command_failed')),
                         'UNSTABLE_AFTER_RECOVERY')

    def test_out_of_bounds_trace_is_rejected(self):
        events = trace('isolated', 'alternate_path', 'link_lost',
                       'mtorr_on_air', 'recovered_command')
        events[-1]['t'] = 121
        self.assertEqual(module.evaluate(events), 'OUT_OF_BOUNDS')


if __name__ == '__main__':
    unittest.main()
