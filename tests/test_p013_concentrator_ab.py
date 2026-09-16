from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
sys.path.insert(0, str(DEPLOY))
SPEC = spec_from_file_location("analyze_concentrator_ab", DEPLOY / "analyze_concentrator_ab.py")
MOD = module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _cfg(minimum: int, maximum: int) -> str:
    return (
        '{"CONCENTRATOR_RAM_TYPE":"high",'
        f'"CONCENTRATOR_MIN_TIME":{minimum},'
        f'"CONCENTRATOR_MAX_TIME":{maximum},'
        '"CONCENTRATOR_ROUTE_ERROR_THRESHOLD":3,'
        '"CONCENTRATOR_DELIVERY_FAILURE_THRESHOLD":1,'
        '"CONCENTRATOR_MAX_HOPS":0}'
    )


def test_candidate_with_lower_quiet_route_rate_is_improved(tmp_path):
    baseline = _write(
        tmp_path,
        "baseline.log",
        f"""[2026-09-16 10:00:00] info: zh:ember: Using stack config {_cfg(5, 60)}.\n"
        "[2026-09-16 10:00:01] info: zh:ember: [CONCENTRATOR] Started source route discovery. 10000ms until next broadcast.\n"
        "[2026-09-16 10:10:00] error: zh:ember: ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE for 23144\n"
        "[2026-09-16 10:20:00] error: zh:ember: ROUTE_ERROR_SOURCE_ROUTE_FAILURE for 26647\n"
        "[2026-09-16 11:00:00] info: end\n""",
    )
    candidate = _write(
        tmp_path,
        "candidate.log",
        f"""[2026-09-16 12:00:00] info: zh:ember: Using stack config {_cfg(10, 120)}.\n"
        "[2026-09-16 12:00:01] info: zh:ember: [CONCENTRATOR] Started source route discovery. 20000ms until next broadcast.\n"
        "[2026-09-16 13:00:00] info: end\n""",
    )
    report = MOD.compare(MOD.summarize(baseline), MOD.summarize(candidate), (5, 60), (10, 120))
    assert report["verdict"] == "IMPROVED"
    assert report["candidate"]["management_scan_markers"] == 0


def test_management_scan_invalidates_ab_sample(tmp_path):
    baseline = _write(
        tmp_path,
        "baseline.log",
        f"[2026-09-16 10:00:00] Using stack config {_cfg(5, 60)}.\n"
        "[2026-09-16 10:30:00] Mgmt_Rtg request sent\n"
        "[2026-09-16 11:00:00] done\n",
    )
    candidate = _write(
        tmp_path,
        "candidate.log",
        f"[2026-09-16 12:00:00] Using stack config {_cfg(10, 120)}.\n"
        "[2026-09-16 13:00:00] done\n",
    )
    report = MOD.compare(MOD.summarize(baseline), MOD.summarize(candidate), (5, 60), (10, 120))
    assert report["verdict"] == "INVALID_SAMPLE"


def test_profile_must_be_observed_in_startup_log(tmp_path):
    baseline = _write(
        tmp_path,
        "baseline.log",
        f"[2026-09-16 10:00:00] Using stack config {_cfg(5, 60)}.\n"
        "[2026-09-16 11:00:00] done\n",
    )
    candidate = _write(
        tmp_path,
        "candidate.log",
        f"[2026-09-16 12:00:00] Using stack config {_cfg(5, 60)}.\n"
        "[2026-09-16 13:00:00] done\n",
    )
    report = MOD.compare(MOD.summarize(baseline), MOD.summarize(candidate), (5, 60), (10, 120))
    assert report["verdict"] == "PROFILE_NOT_CONFIRMED"


def test_hard_regression_is_never_hidden_by_lower_route_churn(tmp_path):
    baseline = _write(
        tmp_path,
        "baseline.log",
        f"[2026-09-16 10:00:00] Using stack config {_cfg(5, 60)}.\n"
        "[2026-09-16 10:20:00] ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE for 23144\n"
        "[2026-09-16 11:00:00] done\n",
    )
    candidate = _write(
        tmp_path,
        "candidate.log",
        f"[2026-09-16 12:00:00] Using stack config {_cfg(10, 120)}.\n"
        "[2026-09-16 12:20:00] An ID conflict was detected for network address '25066'\n"
        "[2026-09-16 13:00:00] done\n",
    )
    report = MOD.compare(MOD.summarize(baseline), MOD.summarize(candidate), (5, 60), (10, 120))
    assert report["verdict"] == "HARD_REGRESSION"
