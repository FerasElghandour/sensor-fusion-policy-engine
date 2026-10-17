"""Runs benchmarks.run_all end-to-end with a small mission count (monkeypatched)
so the report-writing pipeline is exercised without slowing the test suite
down with a full 1000-mission run — that full run is done by CI/manual
invocation of `python -m benchmarks.run_all` itself and by test_v02_acceptance.py."""

import json

from benchmarks import run_all


def test_run_all_writes_all_four_report_files(tmp_path, monkeypatch):
    monkeypatch.setattr(run_all, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(run_all, "MISSION_COUNT", 60)

    metrics = run_all.main()

    assert set(metrics.keys()) == {
        "A_static_threshold_no_compliance",
        "B_deterministic_plus_compliance",
        "C_ai_assisted_plus_compliance",
    }
    for filename in ("benchmark_results.json", "benchmark_summary.csv", "benchmark_report.md", "failure_analysis.md"):
        path = tmp_path / filename
        assert path.exists(), f"{filename} was not written"
        assert path.stat().st_size > 0


def test_run_all_results_json_is_well_formed(tmp_path, monkeypatch):
    monkeypatch.setattr(run_all, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(run_all, "MISSION_COUNT", 60)

    run_all.main()
    data = json.loads((tmp_path / "benchmark_results.json").read_text())

    assert data["mission_count"] == 60
    assert len(data["adversarial_conditions"]) >= 19
    assert "metrics" in data and "sample_outcomes" in data
    for approach_metrics in data["metrics"].values():
        assert "f1_score" in approach_metrics
        assert "unauthorized_leakage_count" in approach_metrics
