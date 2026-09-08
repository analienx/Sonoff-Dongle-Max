import unittest

from runtime.bulk_lane import BulkCommand, coalesce_idempotent, is_coalescible, schedule_bulk


class BulkLaneTests(unittest.TestCase):
    def test_repeated_final_state_is_coalesced_per_segment(self):
        cmds = [
            BulkCommand("group:a", {"state": "ON"}),
            BulkCommand("group:b", {"brightness": 100}),
            BulkCommand("group:a", {"state": "ON", "brightness": 200}),
        ]
        out = coalesce_idempotent(cmds)
        self.assertEqual([c.target for c in out], ["group:b", "group:a"])
        self.assertEqual(out[-1].payload["brightness"], 200)

    def test_toggle_is_barrier_and_never_coalesced(self):
        cmds = [
            BulkCommand("group:a", {"state": "ON"}),
            BulkCommand("group:a", {"toggle": True}),
            BulkCommand("group:a", {"state": "ON"}),
        ]
        out = coalesce_idempotent(cmds)
        self.assertEqual(out, cmds)
        self.assertFalse(is_coalescible(cmds[1]))

    def test_off_is_never_coalesced(self):
        cmds = [BulkCommand("group:a", {"state": "OFF"}), BulkCommand("group:a", {"state": "OFF"})]
        self.assertEqual(coalesce_idempotent(cmds), cmds)

    def test_safety_critical_is_never_coalesced(self):
        cmd = BulkCommand("group:a", {"state": "ON"}, safety_critical=True)
        self.assertFalse(is_coalescible(cmd))

    def test_schedule_has_bounded_reviewed_pacing(self):
        plan = schedule_bulk([
            BulkCommand("g1", {"state": "ON"}),
            BulkCommand("g2", {"state": "ON"}),
            BulkCommand("g3", {"state": "ON"}),
        ], interval_ms=1250)
        self.assertEqual([x.not_before_ms for x in plan], [0, 1250, 2500])

    def test_rejects_global_fast_or_slow_lane(self):
        with self.assertRaises(ValueError):
            schedule_bulk([BulkCommand("g", {"state": "ON"})], interval_ms=999)
        with self.assertRaises(ValueError):
            schedule_bulk([BulkCommand("g", {"state": "ON"})], interval_ms=2001)

    def test_depth_is_checked_before_coalescing(self):
        cmds = [BulkCommand("g", {"state": "ON"}) for _ in range(3)]
        with self.assertRaises(ValueError):
            schedule_bulk(cmds, max_depth=2)

    def test_span_is_bounded(self):
        cmds = [BulkCommand(f"g{i}", {"state": "ON"}) for i in range(4)]
        with self.assertRaises(ValueError):
            schedule_bulk(cmds, interval_ms=2000, max_span_ms=5000)


if __name__ == "__main__":
    unittest.main()
