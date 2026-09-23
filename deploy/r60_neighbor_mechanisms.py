#!/usr/bin/env python3
"""Issue #28: offline, redacted diagnosis from immutable #27 NCP/ZCL evidence.
No Zigbee/HA access. Outputs counts, never device identities or raw network IDs.
"""
import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median
from r60_rf_window import route_firsthop

PHASES = ("before", "after", "after_retry1", "confirm")
VALID_PHASES = ("before", "after_retry1", "confirm")


def read_phase(folder, phase):
    path = Path(folder) / f"r60_placement_v2_{phase}.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("phase") != phase:
        raise ValueError("phase_label_mismatch")
    return result


def read_snapshot(stage, side, private_root):
    meta = stage[side]
    path = Path(meta["private_result_path"]).resolve()
    # Resolve and restrict raw capture reads to the original private spool.
    if not path.is_relative_to(Path(private_root).resolve()):
        raise ValueError("raw_path_outside_private_spool")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if (raw.get("status") != "ok" or raw.get("same_owner_epoch") is not True or
            raw.get("extension_absent_after") is not True):
        raise ValueError("untrusted_snapshot_or_cleanup")
    row = raw.get("snapshot", {})
    entries = row.get("entries")
    if (not isinstance(entries, list) or not isinstance(row.get("count"), int) or
            row["count"] != len(entries) or row["count"] > 26):
        raise ValueError("incomplete_neighbor_table")
    return row


def indexed(row):
    peers = {}
    for item in row["entries"]:
        identity = item.get("longId")
        if not isinstance(identity, str) or len(identity) < 4:
            raise ValueError("invalid_neighbor_identity")
        identity = identity.lower()
        if identity in peers:
            raise ValueError("missing_or_duplicate_ieee")
        for key, maximum in (("averageLqi", 255), ("inCost", 7), ("outCost", 7), ("age", 255)):
            value = item.get(key)
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError("invalid_neighbor_metric")
        peers[identity] = item
    return peers


def metrics(peers):
    values = list(peers.values())
    return {"neighbors": len(values), "outgoing_unknown": sum(p["outCost"] == 0 for p in values),
            "age_over_six": sum(p["age"] > 6 for p in values),
            "median_incoming_lqi": median(p["averageLqi"] for p in values) if values else None,
            "two_way_known": sum(p["outCost"] > 0 for p in values)}



def cached_route_summary(row, departed_shorts=()):
    entries = row.get("source_route_entries")
    if row.get("source_route_entries_truncated") or not isinstance(entries, list):
        return {"status": "not_complete"}
    if len(entries) != row.get("source_route_filled"):
        raise ValueError("partial_source_route_table")
    statuses = Counter()
    departed_hop_references = 0
    for entry in entries:
        result = route_firsthop(row, entry["destination"])
        statuses[result["status"]] += 1
        if (result["status"] == "cached_firsthop_in_neighbor_table" and
                result["firsthop_short"] in departed_shorts):
            departed_hop_references += 1
    return {"status": "complete_cached_not_air_trace", "entries": len(entries),
            "firsthop_status_counts": dict(sorted(statuses.items())),
            "cached_paths_via_subsequently_departed_peers": departed_hop_references}


def phase_summary(stage, first=None, second=None):
    phase = stage["phase"]
    if not stage.get("valid"):
        return {"phase": phase, "valid": False, "excluded_from_rf_analysis": True,
                "reason_class": "ncp_counter_reset_or_wrap" if "ncp_counter" in stage.get("reason", "") else "invalid_capture"}
    if (stage.get("clear_audit", {}).get("status") != "ok" or
            stage["clear_audit"].get("clear_markers") != 0 or
            stage["first"].get("owner_epoch") != stage["second"].get("owner_epoch") or
            stage["zcl"].get("owner_epoch") != stage["first"].get("owner_epoch")):
        raise ValueError("counter_or_owner_integrity_failed")
    a, b = indexed(first), indexed(second)
    gone, entered, retained = a.keys() - b.keys(), b.keys() - a.keys(), a.keys() & b.keys()
    departed = [a[k] for k in gone]
    retained_start = [a[k] for k in retained]
    zcl = stage["zcl"]
    if zcl.get("attempts") != 33 or len(zcl.get("devices", [])) != 11:
        raise ValueError("zcl_cohort_changed")
    return {"phase": phase, "valid": True, "start": metrics(a), "end": metrics(b),
            "departed": len(gone), "entered": len(entered), "retained": len(retained),
            "departed_initial_outgoing_unknown": sum(p["outCost"] == 0 for p in departed),
            "departed_initial_age_over_six": sum(p["age"] > 6 for p in departed),
            "retained_initial_outgoing_unknown": sum(p["outCost"] == 0 for p in retained_start),
            "retained_initial_age_over_six": sum(p["age"] > 6 for p in retained_start),
            "departed_initial_median_lqi": median(p["averageLqi"] for p in departed) if departed else None,
            "retained_initial_median_lqi": median(p["averageLqi"] for p in retained_start) if retained_start else None,
            "retained_outgoing_cost_changed": sum(a[k]["outCost"] != b[k]["outCost"] for k in retained),
            "retained_age_changed": sum(a[k]["age"] != b[k]["age"] for k in retained),
            "verified_zcl": zcl.get("verified"), "zcl_attempts": zcl.get("attempts"),
            "mac_failure_fraction": stage["metrics"].get("mac_failure_fraction"),
            "cca_failures_per_min": stage["metrics"].get("cca_failures_per_min"),
            "neighbor_events_per_min": stage["metrics"].get("neighbor_changes_per_min"),
            "cached_routes_initial": cached_route_summary(first, {a[k]["shortId"] for k in gone}),
            "cached_routes_final": cached_route_summary(second),
            "source_route_occupancy_start": first.get("source_route_filled"),
            "source_route_occupancy_end": second.get("source_route_filled")}


def analyze(stages, snapshots):
    summaries = []
    for phase in PHASES:
        item = stages[phase]
        first, second = snapshots.get(phase, (None, None))
        summaries.append(phase_summary(item, first, second))
    epochs = {stages[p]["first"]["owner_epoch"] for p in VALID_PHASES}
    if len(epochs) != 1:
        raise ValueError("owner_epoch_different_across_valid_positions")
    membership = [set(indexed(snap).keys()) for phase in VALID_PHASES for snap in snapshots[phase]]
    members = set().union(*membership)
    return {"issue": 28, "data_origin": "immutable_issue_27_snapshots", "phases": summaries,
            "unique_observed_direct_peers": len(members),
            "peers_seen_in_four_or_more_of_six_snapshots": sum(sum(peer in sample for sample in membership) >= 4 for peer in members),
            "snapshot_gap_reappearances_not_eviction_count": sum(any(peer in membership[i] and peer not in membership[i+1] and peer in membership[i+2] for i in range(len(membership)-2)) for peer in members),
            "limitations": ["Two endpoint snapshots cannot reveal intermediate admissions, aging transitions, or the reason for an eviction.",
                "Counter-level MAC/CCA failures cannot be assigned to a device, neighbor or route.",
                "ZCL reads test 11 powered routers, not group commands, unprobed devices or direction-specific mesh repair.",
                "Source-route occupancy is not evidence of current route reachability.",
                "A/B positions and times are confounded; do not claim RF causation or a Zigbee-wide reliability rate."],
            "next_test": "Passive, timestamped per-next-hop or external-sniffer evidence tied to real failed commands; separate approved gate required."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, required=True, help="Authorized local sonoff-private directory; never upload it")
    args = parser.parse_args()
    private_root = args.private_root.resolve()
    folder = private_root / "issues" / "27-placement"
    if private_root.name != "sonoff-private" or not folder.is_dir():
        parser.error("invalid_private_spool")
    stages = {phase: read_phase(folder, phase) for phase in PHASES}
    snaps = {phase: (read_snapshot(stages[phase], "first", private_root),
                     read_snapshot(stages[phase], "second", private_root)) for phase in VALID_PHASES}
    print(json.dumps(analyze(stages, snaps), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
