"""Offline safety/syntax contract for the bounded R60 production read-only probe."""
import ast
from pathlib import Path
import re
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'deploy' / 'r60_probe.py'

class R60ProbeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding='utf-8')
        tree = ast.parse(cls.source)
        cls.remote = next(ast.literal_eval(node.value) for node in tree.body
                          if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'REMOTE'
                                  for target in node.targets))

    def test_remote_snippet_is_valid_python(self):
        ast.parse(self.remote)

    def test_no_second_ncp_owner_or_mutating_diagnostics(self):
        for forbidden in ('ezspSet', 'serial.Serial', 'mosquitto_pub',
                          'bridge/request', 'docker restart', 'docker stop',
                          'factoryReset', 'permit_join'):
            self.assertNotIn(forbidden, self.remote)

    def test_route_regex_classifies_example(self):
        match = re.search(r'ROUTE_ERROR_([A-Z_]+) for "(\d+)"',
                          '[2026-09-21 22:05:15] ROUTE_ERROR_SOURCE_ROUTE_FAILURE for "23144"')
        self.assertEqual((match.group(1), match.group(2)),
                         ('SOURCE_ROUTE_FAILURE', '23144'))

if __name__ == '__main__':
    unittest.main()
