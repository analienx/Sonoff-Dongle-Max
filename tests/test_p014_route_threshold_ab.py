from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
sys.path.insert(0, str(DEPLOY))
SPEC = spec_from_file_location("analyze_route_threshold_ab", DEPLOY / "analyze_route_threshold_ab.py")
MOD = module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _cfg(threshold: int) -> str:
    return (
        '{"CONCENTRATOR_RAM_TYPE":"high","CONCENTRATOR_MIN_TIME":5,'
        '"CONCENTRATOR_MAX_TIME":60,'
        f'"CONCENTRATOR_ROUTE_ERROR_THRESHOLD":{threshold},'
        '"CONCENTRATOR_DELIVERY_FAILURE_THRESHOLD":1,"CONCENTRATOR_MAX_HOPS":0}'
    )

def test_threshold1_reduces_same_nwk_burst_and_route_rate(tmp_path):
    baseline = _write(
        tmp_path,
        "baseline.log",
        f"Using stack config {_cfg(3)}.\n"
        "[2026-09-16 10:00:00] start\n"
        "[2026-09-16 10:10:00] ROUTE_ERROR_SOURCE_ROUTE_FAILURE for 1207\n"
        "[2026-09-16 10:10:03] ROUTE_ERROR_SOURCE_ROUTE_FAILURE for 1207\n"
        "[2026-09-16 10:10:05] ROUTE_ERROR_SOURCE_ROUTE_FAILURE for 1207\n"
        "[2026-09-16 10:10:07] ROUTE_ERROR_SOURCE_ROUTE_FAILURE for 1207\n"
        "[2026-09-16 11:00:00] done\n",
    )
    candidate = _write(
        tmp_path,
        "candidate.log",
        f"Using stack config {_cfg(1)}.\n"
        "[2026-09-16 12:00:00] start\n"
        "[2026-09-16 12:10:00] ROUTE_ERROR_SOURCE_ROUTE_FAILURE for 1207\n"
        "[2026-09-16 13:00:00] done\n",
    )
    report = MOD.compare(
        MOD.summarize(baseline), MOD.summarize(candidate),
        baseline_profile=(5, 60, 3), candidate_profile=(5, 60, 1),
    )
    assert report["verdict"] == "IMPROVED"
    assert report["baseline"]["burst"]["max_burst_size"] == 4
    assert report["candidate"]["burst"]["max_burst_size"] == 1

def test_wrong_threshold_is_profile_not_confirmed(tmp_path):
    baseline = _write(tmp_path, "b.log", f"Using stack config {_cfg(3)}.\n[2026-09-16 10:00:00] start\n[2026-09-16 11:00:00] done\n")
    candidate = _write(tmp_path, "c.log", f"Using stack config {_cfg(3)}.\n[2026-09-16 12:00:00] start\n[2026-09-16 13:00:00] done\n")
    report = MOD.compare(MOD.summarize(baseline), MOD.summarize(candidate), baseline_profile=(5, 60, 3), candidate_profile=(5, 60, 1))
    assert report["verdict"] == "PROFILE_NOT_CONFIRMED"


def test_management_scan_invalidates_sample(tmp_path):
    baseline = _write(tmp_path, "b.log", f"Using stack config {_cfg(3)}.\n[2026-09-16 10:00:00] start\n[2026-09-16 10:30:00] Mgmt_Rtg request\n[2026-09-16 11:00:00] done\n")
    candidate = _write(tmp_path, "c.log", f"Using stack config {_cfg(1)}.\n[2026-09-16 12:00:00] start\n[2026-09-16 13:00:00] done\n")
    report = MOD.compare(MOD.summarize(baseline), MOD.summarize(candidate), baseline_profile=(5, 60, 3), candidate_profile=(5, 60, 1))
    assert report["verdict"] == "INVALID_SAMPLE"


def test_hard_regression_wins_over_route_improvement(tmp_path):
    baseline = _write(tmp_path, "b.log", f"Using stack config {_cfg(3)}.\n[2026-09-16 10:00:00] start\n[2026-09-16 10:10:00] ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE for 4926\n[2026-09-16 11:00:00] done\n")
    candidate = _write(tmp_path, "c.log", f"Using stack config {_cfg(1)}.\n[2026-09-16 12:00:00] start\n[2026-09-16 12:30:00] An ID conflict was detected for network address '25066'\n[2026-09-16 13:00:00] done\n")
    report = MOD.compare(MOD.summarize(baseline), MOD.summarize(candidate), baseline_profile=(5, 60, 3), candidate_profile=(5, 60, 1))
    assert report["verdict"] == "HARD_REGRESSION"


def test_inventory_resolves_and_marks_stale_nwk(tmp_path):
    sample = _write(
        tmp_path,
        "routes.log",
        f"Using stack config {_cfg(1)}.\n"
        "[2026-09-16 12:00:00] start\n"
        "[2026-09-16 12:10:00] ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE for 4926\n"
        "[2026-09-16 12:20:00] ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE for 56510\n"
        "[2026-09-16 13:00:00] done\n",
    )
    inventory_path = tmp_path / "devices.json"
    inventory_path.write_text('[{"friendly_name":"KitchenSocketDishwasher","ieee_address":"0xabc","network_address":4926,"type":"Router","model_id":"TS011F","manufacturer":"_TZ3000_cehuw1lw"}]', encoding="utf-8")
    report = MOD.summarize(sample)
    MOD.decorate_targets(report, MOD.load_inventory(inventory_path))
    assert report["route_targets"]["resolved"]["4926"]["friendly_name"] == "KitchenSocketDishwasher"
    assert report["route_targets"]["unresolved"] == {"56510": 1}
