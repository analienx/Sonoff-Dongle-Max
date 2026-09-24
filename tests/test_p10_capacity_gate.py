"""Offline fail-closed checks for existing 60+ router migration capacity."""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "p10_capacity_gate.py"
spec = importlib.util.spec_from_file_location("p10_capacity_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
DIGEST = hashlib.sha256(b"synthetic P10 image").hexdigest()


def inventory(routers=63):
    devices = [{"type": "Coordinator", "ieee_address": "0x" + "0" * 15 + "1"}]
    for n in range(2, routers + 2):
        devices.append({"type": "Router", "ieee_address": "0x" + f"{n:016x}"})
    return devices


def evidence(neighbors=80):
    fields = {name: 200 for name in gate.TABLES}
    fields["neighbor"] = neighbors
    return {"radio_image_sha256": DIGEST, "compiled_tables": fields,
            "private_tclk_demand": 70, "private_link_key_demand": 50,
            "private_direct_child_demand": 20, "private_route_demand": 60,
            "private_source_route_demand": 60}


def operational(devices):
    return {"scope": "existing-network-after-cutover", "radio_image_sha256": DIGEST,
            "duration_seconds": 86400,
            "routers": [{"ieee_address": dev["ieee_address"], "attempts": 100,
                         "acknowledged": 100} for dev in devices if dev["type"] == "Router"],
            "neighbor_table_full_events": 0, "tclk_table_full_events": 0,
            "routing_table_full_events": 0, "source_route_table_full_events": 0,
            "source_route_failures": 0, "bidirectional_link_test_passed": True,
            "groupcast_test_passed": True}


class CapacityGateTests(unittest.TestCase):
    def test_63_existing_routers_require_headroom(self):
        result = gate.evaluate(inventory(), evidence(70), DIGEST, 8)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["resource_checks"]["neighbor"]["minimum_required"], 71)
        self.assertFalse(result["production_migration_authorized"])

    def test_valid_claim_does_not_become_firmware_proof(self):
        result = gate.evaluate(inventory(), evidence(80), DIGEST, 8)
        self.assertEqual(result["verdict"], "NOT_PROVEN")
        self.assertEqual(result["resource_checks"]["neighbor"]["status"], "CLAIMED_SUFFICIENT")
        self.assertEqual(result["real_network_operational_test"]["status"], "NOT_PROVEN")

    def test_even_perfect_synthetic_runtime_claim_is_not_preflight_proof(self):
        devices = inventory()
        result = gate.evaluate(devices, evidence(80), DIGEST, 8, operational(devices))
        self.assertEqual(result["real_network_operational_test"]["status"], "OBSERVED_PASS")
        self.assertEqual(result["verdict"], "NOT_PROVEN")
        self.assertNotIn("ieee_address", json.dumps(result))

    def test_missing_private_key_demand_is_not_proven(self):
        claim = evidence()
        del claim["private_tclk_demand"]
        result = gate.evaluate(inventory(), claim, DIGEST, 8)
        self.assertEqual(result["resource_checks"]["tclk"]["status"], "NOT_PROVEN")

    def test_wrong_image_or_duplicate_inventory_rejected(self):
        with self.assertRaises(ValueError):
            gate.evaluate(inventory(), evidence() | {"radio_image_sha256": "a" * 64}, DIGEST, 8)
        items = inventory()
        items.append(dict(items[-1]))
        with self.assertRaises(ValueError):
            gate.inventory_counts(items)

    def test_operational_samples_must_cover_every_existing_router(self):
        devices = inventory()
        run = operational(devices)
        run["routers"].pop()
        result = gate.operational_checks(run, devices, DIGEST)
        self.assertEqual(result["status"], "FAIL")
        run = operational(devices)
        run["routers"][0]["acknowledged"] = 0
        self.assertEqual(gate.operational_checks(run, devices, DIGEST)["status"], "FAIL")

    def test_error_counters_cannot_be_missing(self):
        devices = inventory()
        run = operational(devices)
        del run["neighbor_table_full_events"]
        with self.assertRaises(ValueError):
            gate.operational_checks(run, devices, DIGEST)

    def test_cli_returns_nonzero_with_hypothetical_perfect_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "image.hex").write_bytes(b"synthetic P10 image")
            (root / "inventory.json").write_text(json.dumps(inventory()))
            (root / "evidence.json").write_text(json.dumps(evidence()))
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                code = gate.main(["--inventory", str(root / "inventory.json"),
                                  "--image", str(root / "image.hex"),
                                  "--capacity-evidence", str(root / "evidence.json")])
            self.assertEqual(code, 3)
            self.assertEqual(json.loads(output.getvalue())["verdict"], "NOT_PROVEN")


if __name__ == "__main__":
    unittest.main()
