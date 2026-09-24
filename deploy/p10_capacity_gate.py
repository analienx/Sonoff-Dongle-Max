"""Fail-closed capacity qualification for the EXISTING Zigbee2MQTT mesh.

Offline input only. A vendor manifest or SYS_VERSION is a CLAIM, not firmware proof.
PASS means a finite observed workload passed; never a universal future guarantee.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

TABLES = ("neighbor", "tclk", "link_keys", "children", "routing", "source_routes")


def positive(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def inventory_counts(payload):
    """Accept a retained Z2M bridge/devices array; never emit device identifiers."""
    devices = payload.get("devices") if isinstance(payload, dict) else payload
    if not isinstance(devices, list) or not devices:
        raise ValueError("Expected nonempty zigbee2mqtt/bridge/devices JSON array")
    ids, counts = set(), {"Router": 0, "EndDevice": 0, "Coordinator": 0}
    for device in devices:
        if not isinstance(device, dict) or device.get("type") not in counts:
            raise ValueError("Unexpected device entry/type in inventory")
        identity = device.get("ieee_address")
        if not isinstance(identity, str) or not identity.startswith("0x") or len(identity) != 18:
            raise ValueError("Inventory requires unique IEEE identifiers privately")
        if identity.lower() in ids:
            raise ValueError("Duplicate device IEEE in inventory")
        ids.add(identity.lower())
        counts[device["type"]] += 1
    if counts["Coordinator"] != 1:
        raise ValueError("Inventory must contain exactly one coordinator")
    return {"routers": counts["Router"], "end_devices": counts["EndDevice"],
            "total_devices": len(devices)}


def checks_for_capacity(counts, doc, image_sha, reserve):
    if not isinstance(doc, dict) or doc.get("radio_image_sha256", "").lower() != image_sha:
        raise ValueError("Evidence does not match bytes of the supplied radio image")
    declared = doc.get("compiled_tables")
    if not isinstance(declared, dict):
        raise ValueError("Missing independently reviewable compiled-table claims")
    # Sixty router devices do not imply sixty *direct* neighbors. The requested
    # >=60-entry neighbor allocation is nevertheless an explicit hard gate.
    needed = {"neighbor": max(60, counts["routers"]) + reserve,
              "tclk": doc.get("private_tclk_demand"),
              "link_keys": doc.get("private_link_key_demand"),
              "children": doc.get("private_direct_child_demand"),
              "routing": doc.get("private_route_demand"),
              "source_routes": doc.get("private_source_route_demand")}
    results = {}
    for name in TABLES:
        capacity = declared.get(name)
        demand = needed[name]
        if type(capacity) is not int or capacity < 0:
            results[name] = {"status": "NOT_PROVEN", "reason": "Compiled allocation missing/invalid"}
        elif type(demand) is not int or demand < 0:
            results[name] = {"status": "NOT_PROVEN", "capacity_claim": capacity,
                             "reason": "Real private network demand has not been measured"}
        else:
            results[name] = {"status": "FAIL" if capacity < demand else "CLAIMED_SUFFICIENT",
                             "capacity_claim": capacity, "minimum_required": demand,
                             "claimed_spare_entries": capacity - demand}
    linked = doc.get("source_build_image_link")
    # This tool cannot authenticate an unsigned, user-editable statement.
    return results, ("UNVERIFIED: " + str(linked or "missing") +
                     "; inspect authenticated vendor build+map and exact running-image provenance")


def operational_checks(doc, inventory, image_sha):
    """Validate finite measured service, not future maximum capacity."""
    if doc is None:
        return {"status": "NOT_PROVEN", "reason": "No existing-mesh test after the cutover"}
    if not isinstance(doc, dict) or doc.get("scope") != "existing-network-after-cutover":
        raise ValueError("Operational evidence must be from the existing network after cutover")
    if doc.get("radio_image_sha256", "").lower() != image_sha:
        raise ValueError("Operational report image hash mismatch")
    duration = positive(doc.get("duration_seconds"), "duration_seconds", 86400)
    samples = doc.get("routers")
    if not isinstance(samples, list):
        raise ValueError("Missing per-router operational samples")
    known = {d["ieee_address"].lower() for d in inventory if d["type"] == "Router"}
    visited, success, total, failed_individual = set(), 0, 0, 0
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("Malformed per-router sample")
        address = sample.get("ieee_address", "").lower()
        if address not in known or address in visited:
            raise ValueError("Unrecognized or duplicated router sample")
        visited.add(address)
        attempts = positive(sample.get("attempts"), "router attempts", 20)
        acknowledgements = positive(sample.get("acknowledged"), "acknowledged")
        if acknowledgements > attempts:
            raise ValueError("More acknowledgments than attempts")
        if acknowledgements / attempts < 0.95:
            failed_individual += 1
        total += attempts
        success += acknowledgements
    blocked_events = ("neighbor_table_full_events", "tclk_table_full_events",
                      "routing_table_full_events", "source_route_table_full_events")
    events = {key: positive(doc.get(key), key) for key in blocked_events}
    source_route_failures = positive(doc.get("source_route_failures"), "source_route_failures")
    delivery = success / total if total else 0.0
    ok = (visited == known and failed_individual == 0 and delivery >= 0.99 and
          source_route_failures <= total / 1000 and
          all(value == 0 for value in events.values()) and
          doc.get("bidirectional_link_test_passed") is True and
          doc.get("groupcast_test_passed") is True)
    return {"status": "OBSERVED_PASS" if ok else "FAIL",
            "duration_seconds": duration, "routers_tested": len(visited),
            "routers_expected": len(known), "routers_below_delivery_threshold": failed_individual,
            "delivery_ratio": round(delivery, 6),
            "capacity_exhaustion_events": events, "source_route_failures": source_route_failures,
            "scope_note": "Result covers recorded conditions/window only; input authenticity and future conditions are not proven"}


def evaluate(inventory, evidence, image_sha, reserve, operational=None):
    counts = inventory_counts(inventory)
    devices = inventory["devices"] if isinstance(inventory, dict) else inventory
    capacity, provenance = checks_for_capacity(counts, evidence, image_sha, reserve)
    service = operational_checks(operational, devices, image_sha)
    failures = [name for name, value in capacity.items() if value["status"] == "FAIL"]
    unknown = [name for name, value in capacity.items() if value["status"] == "NOT_PROVEN"]
    # We cannot prove the running P10 has this compiled capacity from hand-entered
    # JSON. Even OBSERVED_PASS is only a finite workload result, not a preflight pass.
    verdict = "FAIL" if failures or service["status"] == "FAIL" else "NOT_PROVEN"
    return {"verdict": verdict, "inventory": counts, "neighbor_reserve": reserve,
            "local_image_sha256": image_sha, "resource_checks": capacity,
            "claimed_capacity_failures": failures, "unknown_resources": unknown,
            "build_to_running_image_provenance": provenance,
            "real_network_operational_test": service,
            "production_migration_authorized": False,
            "unmet_proof": ["Authenticate actual P10 linked-build table allocations and running-image identity",
                            "Verify network-state migration/rollback before cutover",
                            "Corroborate operational telemetry against live collector and existing router inventory"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True,
                        help="PRIVATE retained zigbee2mqtt/bridge/devices JSON; no extra scans")
    parser.add_argument("--image", type=Path, required=True,
                        help="Actual P10 radio firmware image to fingerprint")
    parser.add_argument("--capacity-evidence", type=Path, required=True,
                        help="Exact image linked-build claims plus independently measured private table demand")
    parser.add_argument("--operational", type=Path,
                        help="Optional PRIVATE measured results from existing mesh after cutover")
    parser.add_argument("--neighbor-reserve", type=int, default=8)
    parser.add_argument("--out", type=Path, help="Create only; sanitized summary without IEEE identifiers")
    args = parser.parse_args(argv)
    try:
        reserve = positive(args.neighbor_reserve, "neighbor reserve")
        if reserve > 64:
            raise ValueError("Neighbor reserve must be <=64")
        image_sha = hashlib.sha256(args.image.read_bytes()).hexdigest()
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        evidence = json.loads(args.capacity_evidence.read_text(encoding="utf-8"))
        operational = (json.loads(args.operational.read_text(encoding="utf-8"))
                       if args.operational is not None else None)
        result = evaluate(inventory, evidence, image_sha, reserve, operational)
        if args.out:
            with args.out.open("x", encoding="utf-8") as out:
                out.write(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 4 if result["verdict"] == "FAIL" else 3
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print("P10_CAPACITY_GATE_ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
