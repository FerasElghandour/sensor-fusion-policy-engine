from concurrent.futures import ThreadPoolExecutor
from threading import Event
from dataclasses import replace
import sqlite3
import pytest
import yaml
from fastapi.testclient import TestClient
from api.config import Settings
from api.main import create_app, SCENARIO_INDEX
from fusion_compliance_loop.policy_engine import DEFAULT_POLICY_PATH


@pytest.fixture
def settings(tmp_path):
    return Settings(state_path=tmp_path / "state.sqlite3", reader_token="reader-test-" + "r" * 32,
                    admin_token="admin-test-" + "a" * 32)


def headers(settings, role="admin"):
    return {"Authorization": "Bearer " + getattr(settings, role + "_token")}


def test_absent_configuration_fails_closed_and_does_not_create_state(tmp_path):
    path = tmp_path / "state.sqlite3"
    with TestClient(create_app(Settings(state_path=path))) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/policy/version").status_code == 503
    assert not path.exists()


def test_invalid_credentials_cannot_read_or_initialize_state(settings):
    with TestClient(create_app(settings)) as client:
        for supplied in ({}, {"Authorization": "Bearer incorrect"}):
            assert client.get("/policy/version", headers=supplied).status_code == 401
        assert client.get("/docs").status_code == 404
    assert not settings.state_path.exists()


def test_reader_cannot_change_policy_or_start_benchmarks(settings):
    with TestClient(create_app(settings), headers=headers(settings, "reader")) as client:
        assert client.get("/policy/version").status_code == 200
        assert client.get("/policy/history").status_code == 403
        assert client.post("/policy/reload", json={"text": DEFAULT_POLICY_PATH.read_text(), "expected_revision": 1}).status_code == 403
        assert client.post("/benchmark/run", json={"mission_count": 10}).status_code == 403


def test_policy_update_reaches_other_workers_and_survives_restart(settings):
    content = yaml.safe_load(DEFAULT_POLICY_PATH.read_text())
    content["policy_version"] = "2.0.0"
    # Make the public-camera catch-all reject; this proves scenarios actually
    # use the configured policy rather than an unrelated default engine.
    catchall = next(r for r in content["rules"] if r["rule_id"] == "DEFAULT_PERMIT")
    catchall.update(enforcement_action="REJECT", restricted_fields=["*"])
    with TestClient(create_app(settings), headers=headers(settings)) as first:
        response = first.post("/policy/reload", json={"text": yaml.safe_dump(content), "expected_revision": 1})
        assert response.status_code == 200 and response.json()["revision"] == 2
        with TestClient(create_app(settings), headers=headers(settings, "reader")) as second:
            result = second.get("/scenarios/normal_matching")
            assert result.status_code == 200
            assert result.json()["camera_approved"] is False
            assert result.json()["policy"]["revision"] == 2
            conclusion = result.json()["conclusion_id"]
            assert first.get(f"/decisions/{conclusion}/provenance").json()["policy_revision"] == 2
    with TestClient(create_app(settings), headers=headers(settings)) as restarted:
        assert restarted.get("/policy/version").json()["revision"] == 2
        assert restarted.get(f"/decisions/{conclusion}/explanation").status_code == 200
        assert restarted.get(f"/decisions/{conclusion}/audit-log").json()["log"]
        nodes = restarted.get(f"/decisions/{conclusion}/provenance").json()["provenance_nodes"]
        assert nodes and all(node["payload"].get("rejected") is True for node in nodes)
        assert len(restarted.get("/policy/history").json()["changes"]) == 2


def test_revision_is_required_and_stale_update_gets_conflict(settings):
    content = yaml.safe_load(DEFAULT_POLICY_PATH.read_text())
    content["policy_version"] = "2.0.0"
    with TestClient(create_app(settings), headers=headers(settings)) as client:
        assert client.post("/policy/reload", json={"text": yaml.safe_dump(content)}).status_code == 422
        assert client.post("/policy/reload", json={"text": yaml.safe_dump(content), "expected_revision": 1}).status_code == 200
        assert client.post("/policy/reload", json={"text": DEFAULT_POLICY_PATH.read_text(), "expected_revision": 1}).status_code == 409
        assert client.get("/policy/version").json()["revision"] == 2


def test_chunked_body_limit_cannot_be_bypassed_without_content_length(settings):
    with TestClient(create_app(settings), headers=headers(settings)) as client:
        response = client.post("/policy/validate", content=(b"x" * 32768 for _ in range(3)))
        assert response.status_code == 413
        assert "X-Request-ID" in response.headers


@pytest.mark.parametrize("payload", [{"mission_count": 501}, {"mission_count": -1},
    {"mission_count": 10, "seed": -1}, {"mission_count": True}, {"mission_count": 10, "write_reports": True}])
def test_benchmark_work_and_side_effects_are_bounded(settings, payload):
    with TestClient(create_app(settings), headers=headers(settings)) as client:
        assert client.post("/benchmark/run", json=payload).status_code == 422


def test_benchmark_does_not_mutate_policy_or_shared_configuration(settings):
    from benchmarks import run_all
    original = (run_all.MISSION_COUNT, run_all.SEED, run_all.REPORTS_DIR)
    with TestClient(create_app(settings), headers=headers(settings)) as client:
        before = client.get("/policy/version").json()
        response = client.post("/benchmark/run", json={"mission_count": 10, "seed": 12})
        assert response.status_code == 200
        assert response.json()["metrics"]["B_deterministic_plus_compliance"]["metric_version"] == "2.0"
        assert client.get("/policy/version").json() == before
    assert (run_all.MISSION_COUNT, run_all.SEED, run_all.REPORTS_DIR) == original


def test_overload_is_rejected_and_capacity_recovers(settings, monkeypatch):
    started, release = Event(), Event()
    original = SCENARIO_INDEX["normal_matching"]
    def paused(policy_engine=None):
        started.set()
        if not release.wait(5):
            raise RuntimeError("test synchronization timed out")
        return original(policy_engine=policy_engine)
    monkeypatch.setitem(SCENARIO_INDEX, "normal_matching", paused)
    with TestClient(create_app(replace(settings, max_parallel_jobs=1)), headers=headers(settings)) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.get, "/scenarios/normal_matching")
            try:
                assert started.wait(5)
                rejected = client.get("/scenarios/normal_matching")
                assert rejected.status_code == 429 and rejected.headers["Retry-After"] == "1"
            finally:
                release.set()
            assert pending.result(timeout=10).status_code == 200
        assert client.get("/scenarios/normal_matching").status_code == 200


def test_storage_corruption_cannot_fall_back_to_default_policy(settings):
    with TestClient(create_app(settings), headers=headers(settings)) as client:
        assert client.get("/ready").status_code == 200
        with sqlite3.connect(settings.state_path) as conn:
            conn.execute("UPDATE policy_revisions SET sha256='corrupted'")
        assert client.get("/ready").status_code == 503
        assert client.get("/scenarios/normal_matching").status_code == 503


def test_unexpected_errors_and_logs_do_not_disclose_raw_payloads_or_credentials(settings, monkeypatch, caplog):
    def fail(policy_engine=None):
        raise RuntimeError("synthetic-sensitive-exception-detail")
    monkeypatch.setitem(SCENARIO_INDEX, "normal_matching", fail)
    with TestClient(create_app(settings), headers=headers(settings)) as client:
        response = client.get("/scenarios/normal_matching")
        assert response.status_code == 500
        assert response.json() == {"detail": "request failed"}
        assert response.headers["Cache-Control"] == "no-store"
    assert "synthetic-sensitive-exception-detail" not in caplog.text
    assert settings.admin_token not in caplog.text


def test_weak_or_shared_credentials_are_rejected(settings):
    with pytest.raises(ValueError):
        replace(settings, admin_token="weak")
    with pytest.raises(ValueError):
        replace(settings, admin_token=settings.reader_token)


def test_non_ascii_invalid_token_is_rejected_without_server_error(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/policy/version", headers={b"Authorization": b"Bearer invalid-\xff"})
        assert response.status_code == 401
