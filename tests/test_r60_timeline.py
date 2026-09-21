"""Classifier and transport safety contracts for R60 passive timeline collectors."""
import ast
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'deploy'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TimelineTests(unittest.TestCase):
    def test_remote_snippets_parse_and_do_not_mutate(self):
        for name in ('r60_restart_timeline','r60_ota_activity'):
            with self.subTest(name=name):
                module = load(name)
                ast.parse(module.REMOTE)
                for forbidden in ('docker restart','docker stop','docker kill','docker cp',
                                  'mqtt_pub','bridge/request','serialport','ezsp',
                                  'firmware flash','networkmap', 'configuration.yaml\').write'):
                    self.assertNotIn(forbidden, module.REMOTE)

    def test_no_broad_zigbee_update_is_mistaken_for_ota(self):
        module = load('r60_restart_timeline')
        match = re.search(r"'ota_explicit':r'([^']+)'", module.REMOTE)
        self.assertIsNotNone(match)
        pat = re.compile(match.group(1))
        self.assertIsNone(pat.search('zigbee2mqtt state update: device temperature 20'))
        self.assertIsNotNone(pat.search('Checking if OTA update available'))

    def test_ota_availability_is_not_counted_as_transfer(self):
        module = load('r60_ota_activity')
        patterns = {}
        for key in ('ota_available_or_check','ota_transfer_start','ota_transfer_progress','ota_transfer_finish'):
            m = re.search("'"+key+"':r'([^']+)'", module.REMOTE)
            self.assertIsNotNone(m)
            patterns[key] = re.compile(m.group(1))
        message = "Checking if OTA update available for 'device'"
        self.assertTrue(patterns['ota_available_or_check'].search(message))
        for key in ('ota_transfer_start','ota_transfer_progress','ota_transfer_finish'):
            self.assertFalse(patterns[key].search(message),key)
        self.assertTrue(patterns['ota_transfer_start'].search("OTA updating 'device' to latest firmware"))


if __name__ == '__main__': unittest.main()
