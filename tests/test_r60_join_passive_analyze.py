"""Offline regression tests: never publish private log identities or NWK values."""
import importlib.util
import json
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy' / 'r60_join_passive_analyze.py'
spec = importlib.util.spec_from_file_location('r60_join_passive_analyze', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class JoinPassiveTests(unittest.TestCase):
    def test_join_failure_then_success_and_other_router_errors(self):
        ieee = '0x00124b0000aa00bb'
        lines = [
            '2026-09-22T16:41:00.000Z ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE for "500".',
            "2026-09-22T16:41:17.999Z z2m: Device 'BedroomSocketCabinetRight' joined",
            '2026-09-22T16:41:33.999Z Interview - active endpoints request failed for '+ieee+' (Error: {"target":59924})',
            '2026-09-22T16:41:43.999Z Interview - first modelId retrieval attempt failed, retrying after 10 seconds...',
            '2026-09-22T16:42:03.350Z ROUTE_ERROR_SOURCE_ROUTE_FAILURE for "59924".',
            "2026-09-22T16:42:03.680Z z2m: Successfully interviewed 'BedroomSocketCabinetRight', device has successfully been paired",
            '2026-09-22T16:42:04.000Z ROUTE_ERROR_SOURCE_ROUTE_FAILURE for "300".',
            "2026-09-22T16:47:08.000Z z2m: Failed to read state of 'WorkroomTableRightDimmer' after reconnect",
        ]
        result = module.analyze(lines, excluded=['WorkroomTableRightDimmer'])
        self.assertEqual(result['phases']['during_interview']['events']['route_errors_for_joining_nwk'],1)
        self.assertEqual(result['phases']['post_interview']['events']['intentionally_unpowered_read_error'],1)
        self.assertEqual(result['phases']['post_interview']['events']['route_errors_for_joining_nwk'] if 'route_errors_for_joining_nwk' in result['phases']['post_interview']['events'] else 0, 0)
        self.assertNotIn(ieee,json.dumps(result))
        self.assertNotIn('59924',json.dumps(result))

    def test_subsecond_order_places_two_failures_after_success(self):
        lines = [
            "2026-09-22T16:41:17.912977000Z z2m: Device 'Socket' joined",
            '2026-09-22T16:41:33.188667000Z Interview - active endpoints request failed (Error: {"target":59924})',
            '2026-09-22T16:42:03.350157000Z ROUTE_ERROR_SOURCE_ROUTE_FAILURE for "59924".',
            "2026-09-22T16:42:03.681218000Z z2m: Successfully interviewed 'Socket', device has successfully been paired",
            '2026-09-22T16:42:03.752126000Z ROUTE_ERROR_SOURCE_ROUTE_FAILURE for "59924".',
            '2026-09-22T16:42:03.851266000Z ROUTE_ERROR_SOURCE_ROUTE_FAILURE for "59924".',
        ]
        result = module.analyze(lines)
        self.assertEqual(result['phases']['during_interview']['events']['route_errors_for_joining_nwk'], 1)
        self.assertEqual(result['phases']['post_interview']['events']['route_errors_for_joining_nwk'], 2)
        self.assertNotIn('59924', json.dumps(result))

    def test_missing_join_cannot_invent_join_target(self):
        result = module.analyze(['2026-09-22T16:41:00.000Z ROUTE_ERROR_SOURCE_ROUTE_FAILURE for "12345".'])
        self.assertIsNone(result['join_started_utc'])
        self.assertFalse(result['joining_nwk_resolved_privately'])
        self.assertEqual(result['phases']['pre_join']['events']['route_errors'], 1)
