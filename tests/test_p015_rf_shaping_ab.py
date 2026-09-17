from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
sys.path.insert(0, str(DEPLOY))
SPEC = spec_from_file_location("analyze_rf_shaping_ab", DEPLOY / "analyze_rf_shaping_ab.py")
MOD = module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _cfg() -> str:
    return (
        '{"CONCENTRATOR_RAM_TYPE":"high","CONCENTRATOR_MIN_TIME":5,'
        '"CONCENTRATOR_MAX_TIME":60,"CONCENTRATOR_ROUTE_ERROR_THRESHOLD":3,'
        '"CONCENTRATOR_DELIVERY_FAILURE_THRESHOLD":1}'
    )


def _window(tmp_path: Path, name: str, count: int, *, extra: str = "") -> dict[str, object]:
    lines = [f"Using stack config {_cfg()}.", "[2026-09-17 10:00:00] start"]
    for i in range(count):
        minute = 2 + i * 4
        lines.append(
            f"[2026-09-17 10:{minute:02d}:00] "
            f"ROUTE_ERROR_SOURCE_ROUTE_FAILURE for {1000 + i}"
        )
    if extra:
        lines.append(extra)
    lines.append("[2026-09-17 11:00:00] done")
    return MOD.summarize(_write(tmp_path, name, "\n".join(lines) + "\n"))


def test_three_db_candidate_accepts_decisive_route_improvement(tmp_path):
    baseline = _window(tmp_path, "baseline.log", 10)
    candidate = _window(tmp_path, "candidate.log", 6)
    report = MOD.compare(
        baseline,
        candidate,
        baseline_attenuation_db=0.0,
        candidate_attenuation_db=3.0,
    )
    assert report["verdict"] == "IMPROVED"
    assert report["experiment"]["attenuation_delta_db"] == 3.0


def test_small_change_is_not_overclaimed(tmp_path):
    baseline = _window(tmp_path, "baseline.log", 10)
    candidate = _window(tmp_path, "candidate.log", 8)
    report = MOD.compare(
        baseline,
        candidate,
        baseline_attenuation_db=0.0,
        candidate_attenuation_db=3.0,
    )
    assert report["verdict"] == "NO_CLEAR_CHANGE"


def test_route_regression_rejects_candidate(tmp_path):
    baseline = _window(tmp_path, "baseline.log", 10)
    candidate = _window(tmp_path, "candidate.log", 13)
    report = MOD.compare(
        baseline,
        candidate,
        baseline_attenuation_db=0.0,
        candidate_attenuation_db=3.0,
    )
    assert report["verdict"] == "WORSE_ROUTING"


def test_hard_regression_overrides_lower_route_rate(tmp_path):
    baseline = _window(tmp_path, "baseline.log", 10)
    candidate = _window(
        tmp_path,
        "candidate.log",
        5,
        extra="[2026-09-17 10:50:00] An ID conflict was detected for network address '25066'",
    )
    report = MOD.compare(
        baseline,
        candidate,
        baseline_attenuation_db=0.0,
        candidate_attenuation_db=3.0,
    )
    assert report["verdict"] == "HARD_REGRESSION"


def test_management_scan_invalidates_sample(tmp_path):
    baseline = _window(tmp_path, "baseline.log", 10)
    candidate = _window(
        tmp_path,
        "candidate.log",
        5,
        extra="[2026-09-17 10:50:00] Mgmt_Rtg request",
    )
    report = MOD.compare(
        baseline,
        candidate,
        baseline_attenuation_db=0.0,
        candidate_attenuation_db=3.0,
    )
    assert report["verdict"] == "INVALID_SAMPLE"


def test_non_increasing_attenuation_is_invalid_experiment(tmp_path):
    baseline = _window(tmp_path, "baseline.log", 10)
    candidate = _window(tmp_path, "candidate.log", 5)
    report = MOD.compare(
        baseline,
        candidate,
        baseline_attenuation_db=0.0,
        candidate_attenuation_db=0.0,
    )
    assert report["verdict"] == "INVALID_EXPERIMENT"
