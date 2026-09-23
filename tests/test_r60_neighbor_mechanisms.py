"""Offline regressions for issue #28: never queries HA, publishes device IDs or changes radio."""
import copy
import importlib.util
import json
import tempfile
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "deploy" / "r60_neighbor_mechanisms.py"
sys.path.insert(0,str(SRC.parent))
spec = importlib.util.spec_from_file_location("r60_neighbor_mechanisms", SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def peer(identity, short, outcost, age, lqi):
    return {"longId": identity, "shortId": short, "outCost": outcost,
            "age": age, "averageLqi": lqi, "inCost": 2}


def sample(left=True):
    rows = ([peer("secret-alpha", 100, 0, 3, 130), peer("secret-beta", 200, 2, 7, 100)]
            if left else [peer("secret-beta", 200, 2, 3, 90), peer("secret-gamma", 300, 2, 3, 110)])
    routes = [{"index": 0, "destination": 100, "closerIndex": 255},
              {"index": 1, "destination": 200, "closerIndex": 255}]
    return {"count": len(rows), "entries": rows, "source_route_filled": 2,
            "source_route_entries": routes, "source_route_entries_truncated": False}


def stage(name="before"):
    return {"phase": name, "valid": True, "first": {"owner_epoch": "owner"},
            "second": {"owner_epoch": "owner"}, "clear_audit": {"status": "ok", "clear_markers": 0},
            "zcl": {"owner_epoch": "owner", "attempts": 33, "verified": 33,
                    "devices": [{"name": "PRIVATE_DEVICE"} for _ in range(11)]},
            "metrics": {"mac_failure_fraction": .1, "cca_failures_per_min": 3,
                        "neighbor_changes_per_min": 10}}


class NeighborMechanismTests(unittest.TestCase):
    def test_departure_is_not_equivalent_to_preexisting_aging(self):
        result = m.phase_summary(stage(), sample(True), sample(False))
        self.assertEqual(result["departed"], 1)
        self.assertEqual(result["departed_initial_outgoing_unknown"], 1)
        self.assertEqual(result["departed_initial_age_over_six"], 0)
        self.assertEqual(result["retained_initial_age_over_six"], 1)
        self.assertEqual(result["cached_routes_initial"]["cached_paths_via_subsequently_departed_peers"], 1)
        self.assertEqual(result["cached_routes_final"]["firsthop_status_counts"]["cached_firsthop_not_neighbor"], 1)
        for private in ("secret-alpha", "secret-beta", "PRIVATE_DEVICE", "firsthop_short", "longId", "shortId"):
            self.assertNotIn(private, json.dumps(result))

    def test_rejected_hourly_clear_remains_excluded(self):
        wrong = stage("after")
        wrong.update(valid=False, reason="ncp_counter_reset_or_wrap; discard_window")
        self.assertEqual(m.phase_summary(wrong)["reason_class"], "ncp_counter_reset_or_wrap")
        self.assertNotIn("cached_routes_initial", m.phase_summary(wrong))

    def test_counter_clear_owner_cohort_and_duplicate_rejected(self):
        for change in (lambda d: d["clear_audit"].update(clear_markers=1),
                       lambda d: d["second"].update(owner_epoch="other"),
                       lambda d: d["zcl"].update(attempts=32)):
            data = stage();change(data)
            with self.assertRaises(ValueError):m.phase_summary(data, sample(), sample(False))
        row = sample();row["entries"][1]["longId"] = row["entries"][0]["longId"]
        with self.assertRaises(ValueError):m.indexed(row)
        row = sample();row["entries"][0]["outCost"] = 9
        with self.assertRaises(ValueError):m.indexed(row)

    def test_incomplete_source_route_rejected(self):
        row = sample();row["source_route_entries"].pop()
        with self.assertRaisesRegex(ValueError, "partial_source_route_table"):m.cached_route_summary(row)
        row["source_route_entries_truncated"] = True
        self.assertEqual(m.cached_route_summary(row)["status"], "not_complete")

    def test_analyze_reappearance_is_observed_not_eviction_count(self):
        cases = {label: stage(label) for label in m.PHASES}
        cases["after"].update(valid=False, reason="ncp_counter_reset_or_wrap")
        observations = {label: (sample(True), sample(False)) for label in m.VALID_PHASES}
        out = m.analyze(cases, observations)
        self.assertEqual(out["unique_observed_direct_peers"], 3)
        self.assertGreaterEqual(out["snapshot_gap_reappearances_not_eviction_count"], 1)
        self.assertEqual(out["phases"][1]["valid"], False)
        cases["confirm"]["first"]["owner_epoch"] = "other"
        with self.assertRaises(ValueError):m.analyze(cases, observations)

    def test_snapshot_path_and_cleanup_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "raw_path_outside_private_spool"):
                m.read_snapshot({"first": {"private_result_path": str(root.parent / "different.json")}}, "first", root)
            path = root / "raw.json"
            path.write_text(json.dumps({"status": "ok", "same_owner_epoch": True,
                                        "extension_absent_after": False, "snapshot": sample()}))
            with self.assertRaisesRegex(ValueError, "untrusted_snapshot_or_cleanup"):
                m.read_snapshot({"first": {"private_result_path": str(path)}}, "first", root)
            payload = json.loads(path.read_text());payload["extension_absent_after"] = True
            path.write_text(json.dumps(payload))
            self.assertEqual(m.read_snapshot({"first": {"private_result_path": str(path)}}, "first", root)["count"], 2)


if __name__ == "__main__":
    unittest.main()
