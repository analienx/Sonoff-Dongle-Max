"""All offline: no USB, radio, network, coordinator or production imports."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "deploy" / "p10_neighbor_capacity.py"
spec = importlib.util.spec_from_file_location("p10_neighbor_capacity", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def neighbor(index, *, router=True):
    return {"ieee": f"{index + 1:016x}", "device_type": 1 if router else 2,
            "rx_on_when_idle": 1, "lqi": 120}


def capture(size=60, page_size=14):
    pages = []
    for start in range(0, size, page_size):
        records = [neighbor(i) for i in range(start, min(start + page_size, size))]
        pages.append({"status": 0, "neighbor_table_entries": size,
                      "start_index": start, "neighbor_table_list_count": len(records), "entries": records})
    return {"timestamp_utc": "2026-09-23T12:00:00+00:00", "pages": pages}


class NeighborEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = Path(self.tmp.name) / "test-image.hex"
        self.image.write_bytes(b"synthetic-only")

    def document(self, records):
        return {"scope": "isolated-disposable-network", "observer_role": "coordinator",
                "source": "ZDO-Mgmt_Lqi_rsp", "radio_image_sha256": mod.digest(self.image),
                "captures": records}

    def test_sixty_entries_are_only_sequential_paged_evidence(self):
        result = mod.snapshot_report(self.document([capture()]), self.image, 60)
        self.assertEqual(result["observed_router_entries_peak"], 60)
        self.assertTrue(result["target_router_entries_in_complete_pagination"])
        self.assertFalse(result["atomic_simultaneity_verified"])
        self.assertEqual(result["compiled_maximum"], "UNKNOWN")
        self.assertNotIn("0000000000000001", json.dumps(result))

    def test_twentysix_does_not_meet_target(self):
        result = mod.snapshot_report(self.document([capture(26)]), self.image, 60)
        self.assertFalse(result["target_router_entries_in_complete_pagination"])

    def test_stable_identity_count_not_sum_of_snapshots(self):
        first, second = capture(29), capture(29)
        second["timestamp_utc"] = "2026-09-23T12:01:00+00:00"
        second["pages"][0]["entries"][0]["ieee"] = "fffffffffffffffe"
        result = mod.snapshot_report(self.document([first, second]), self.image, 27)
        self.assertEqual(result["router_identifiers_present_in_all_captures"], 28)
        self.assertEqual(result["observed_router_entries_peak"], 29)

    def test_nonrouter_not_counted_as_router(self):
        c = capture(60)
        c["pages"][0]["entries"][0]["device_type"] = 2
        result = mod.snapshot_report(self.document([c]), self.image, 60)
        self.assertEqual(result["observed_router_entries_peak"], 59)
        self.assertFalse(result["target_router_entries_in_complete_pagination"])

    def test_reject_missing_page(self):
        c = capture()
        c["pages"].pop(1)
        with self.assertRaises(ValueError):
            mod.snapshot_report(self.document([c]), self.image, 60)

    def test_reject_count_change_or_duplicate(self):
        for mutation in ("change", "duplicate"):
            c = capture()
            if mutation == "change":
                c["pages"][1]["neighbor_table_entries"] = 59
            else:
                c["pages"][1]["entries"][0]["ieee"] = c["pages"][0]["entries"][0]["ieee"]
            with self.assertRaises(ValueError):
                mod.snapshot_report(self.document([c]), self.image, 60)

    def test_reject_failed_response_and_invalid_type(self):
        for field, value in (("status", 1), ("neighbor_table_list_count", True)):
            c = capture()
            c["pages"][0][field] = value
            with self.assertRaises(ValueError):
                mod.snapshot_report(self.document([c]), self.image, 60)

    def test_reject_production_or_wrong_image(self):
        doc = self.document([capture()])
        doc["scope"] = "production-network"
        with self.assertRaises(ValueError):
            mod.snapshot_report(doc, self.image, 60)
        doc["scope"] = "isolated-disposable-network"
        doc["radio_image_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            mod.snapshot_report(doc, self.image, 60)

    def test_reject_nonmonotonic_timestamps(self):
        c = capture()
        with self.assertRaises(ValueError):
            mod.snapshot_report(self.document([c, c]), self.image, 60)

    def test_macro_dump_reports_claim_not_actual_maximum(self):
        path = Path(self.tmp.name) / "preprocessed-macros.txt"
        path.write_text("#define OTHER 1\n#define MAX_NEIGHBOR_ENTRIES (60U)\n", encoding="utf-8")
        result = mod.macro_report(path, self.image)
        self.assertEqual(result["configured_neighbor_entries_declared"], 60)
        self.assertEqual(result["exact_running_image_link"], "UNVERIFIED")

    def test_macro_dump_rejects_conditional_and_duplicate_values(self):
        path = Path(self.tmp.name) / "macros.txt"
        for text in ("#define MAX_NEIGHBOR_ENTRIES (26 + 34)\n",
                     "#define MAX_NEIGHBOR_ENTRIES 26\n#define MAX_NEIGHBOR_ENTRIES 60\n",
                     "#if 0\n#define MAX_NEIGHBOR_ENTRIES 60\n#endif\n"):
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                mod.macro_report(path, self.image)


if __name__ == "__main__":
    unittest.main()
