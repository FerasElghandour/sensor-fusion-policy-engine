import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.config import Settings
from fusion_compliance_loop.policy_engine import DEFAULT_POLICY_PATH

@pytest.fixture(autouse=True)
def _isolated_service(tmp_path):
    global client
    settings = Settings(state_path=tmp_path / "service.sqlite3",
                        reader_token="reader-test-" + "r" * 32,
                        admin_token="admin-test-" + "a" * 32)
    with TestClient(create_app(settings), headers={"Authorization": "Bearer " + settings.admin_token}) as active:
        client = active
        yield


def test_list_scenarios():
    r = client.get("/scenarios")
    assert r.status_code == 200
    assert "normal_matching" in r.json()["scenarios"]


def test_run_scenario_normal_matching():
    r = client.get("/scenarios/normal_matching")
    assert r.status_code == 200
    body = r.json()
    assert body["confidence_before"] == 0.55
    assert body["confidence_after"] > body["confidence_before"]
    assert "conclusion_id" in body


def test_run_unknown_scenario_404():
    r = client.get("/scenarios/does-not-exist")
    assert r.status_code == 404


def test_audit_log_invalid_format_400():
    r = client.get("/scenarios/normal_matching/audit-log?fmt=xml")
    assert r.status_code == 400


def test_policy_version():
    r = client.get("/policy/version")
    assert r.status_code == 200
    body = r.json()
    assert body["policy_id"] == "fusion-compliance-baseline"
    # 6 original rules + 3 added in the v0.3 compliance-risk audit.
    assert body["rule_count"] == 9


def test_policy_validate_valid_and_invalid():
    good_text = DEFAULT_POLICY_PATH.read_text()
    r = client.post("/policy/validate", json={"text": good_text})
    assert r.status_code == 200
    assert r.json()["valid"] is True

    r = client.post("/policy/validate", json={"text": "not: [valid"})
    assert r.status_code == 200
    assert r.json()["valid"] is False
    assert "error" in r.json()


def test_policy_validate_rejects_empty_text():
    r = client.post("/policy/validate", json={"text": "   "})
    assert r.status_code == 400


def test_policy_reload_valid_then_invalid_preserves_active():
    import yaml

    data = yaml.safe_load(DEFAULT_POLICY_PATH.read_text())
    data["policy_version"] = "9.9.9"
    r = client.post("/policy/reload", json={"text": yaml.safe_dump(data), "expected_revision": 1})
    assert r.status_code == 200
    assert r.json()["policy_version"] == "9.9.9"

    r2 = client.post("/policy/reload", json={"text": "definitely not valid: [", "expected_revision": 2})
    assert r2.status_code == 422

    r3 = client.get("/policy/version")
    assert r3.json()["policy_version"] == "9.9.9"  # last valid reload preserved, not clobbered


def test_adversarial_conditions_list():
    r = client.get("/adversarial/conditions")
    assert r.status_code == 200
    assert r.json()["count"] >= 19


def test_adversarial_run_one():
    r = client.get("/adversarial/run-one?seed=7&index=0")
    assert r.status_code == 200
    body = r.json()
    assert "mission_id" in body
    assert "ground_truth" in body
    assert "conclusion_id" in body


def test_adversarial_run_one_rejects_negative_index():
    r = client.get("/adversarial/run-one?index=-1")
    assert r.status_code == 422


def test_benchmark_run_in_memory_small():
    r = client.post("/benchmark/run", json={"mission_count": 50, "seed": 1, "write_reports": False})
    assert r.status_code == 200
    body = r.json()
    assert body["wrote_reports"] is False
    assert "C_ai_assisted_plus_compliance" in body["metrics"]


def test_benchmark_run_rejects_out_of_range_mission_count():
    r = client.post("/benchmark/run", json={"mission_count": 0})
    assert r.status_code == 422
    r2 = client.post("/benchmark/run", json={"mission_count": 999999})
    assert r2.status_code == 422


def test_benchmark_results_reads_disk_report(tmp_path, monkeypatch):
    from benchmarks import run_all as benchmark_run_all

    monkeypatch.setattr(benchmark_run_all, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(benchmark_run_all, "MISSION_COUNT", 40)
    benchmark_run_all.main()

    r = client.get("/benchmark/results")
    assert r.status_code == 200
    assert r.json()["mission_count"] == 40


def test_decision_provenance_and_explanation_round_trip():
    scenario_response = client.get("/scenarios/normal_matching")
    conclusion_id = scenario_response.json()["conclusion_id"]

    r = client.get(f"/decisions/{conclusion_id}/provenance")
    assert r.status_code == 200
    assert r.json()["provenance_chain"]

    r2 = client.get(f"/decisions/{conclusion_id}/explanation")
    assert r2.status_code == 200
    assert r2.json()["explanation"]


def test_decision_lookup_404_for_unknown_id():
    r = client.get("/decisions/does-not-exist/provenance")
    assert r.status_code == 404
    r2 = client.get("/decisions/does-not-exist/explanation")
    assert r2.status_code == 404
