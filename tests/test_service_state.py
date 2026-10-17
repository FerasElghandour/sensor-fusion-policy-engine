import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest
import yaml
from fusion_compliance_loop.policy_engine import DEFAULT_POLICY_PATH, PolicyLoadError
from fusion_compliance_loop.service_state import RevisionConflict, ServiceState


def policy(version):
    content = yaml.safe_load(DEFAULT_POLICY_PATH.read_text())
    content["policy_version"] = version
    return yaml.safe_dump(content)


def test_state_survives_recreation_and_is_shared_by_instances(tmp_path):
    path = tmp_path / "service.sqlite3"
    first, second = ServiceState(path), ServiceState(path)
    first.replace_policy(policy("2.0.0"), 1)
    second.remember_decision("d1", {"explanation": "A retained synthetic decision."})
    restarted = ServiceState(path)
    assert restarted.current_policy().public()["policy_version"] == "2.0.0"
    assert first.decision("d1") == restarted.decision("d1")
    assert [r["revision"] for r in restarted.policy_history()] == [2, 1]


def test_invalid_or_stale_update_preserves_policy_and_audit(tmp_path):
    store = ServiceState(tmp_path / "state.sqlite3")
    original = store.current_policy()
    with pytest.raises(PolicyLoadError):
        store.replace_policy("not: [valid", 1)
    store.replace_policy(policy("2.0.0"), 1)
    with pytest.raises(RevisionConflict):
        store.replace_policy(policy("3.0.0"), 1)
    assert store.current_policy().revision == 2
    assert len(store.policy_history()) == 2
    assert original.revision == 1


def test_changed_content_requires_a_new_version_and_identical_update_is_idempotent(tmp_path):
    store = ServiceState(tmp_path / "state.sqlite3")
    assert store.replace_policy(DEFAULT_POLICY_PATH.read_text(), 1).revision == 1
    content = yaml.safe_load(DEFAULT_POLICY_PATH.read_text())
    content["rules"][0]["description"] = "Different policy content."
    with pytest.raises(RevisionConflict, match="new policy_version"):
        store.replace_policy(yaml.safe_dump(content), 1)
    assert len(store.policy_history()) == 1


def test_old_content_can_be_restored_as_a_new_audited_revision(tmp_path):
    store = ServiceState(tmp_path / "state.sqlite3")
    original = store.current_policy()
    store.replace_policy(policy("2.0.0"), 1)
    restored = store.replace_policy(original.text, 2)
    assert restored.revision == 3 and restored.sha256 == original.sha256
    assert [r["prior_revision"] for r in store.policy_history()] == [2, 1, None]


def test_decision_retention_is_bounded_and_persisted(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = ServiceState(path, decision_limit=2)
    for i in range(3):
        store.remember_decision(str(i), {"explanation": f"Synthetic result {i}."})
    restarted = ServiceState(path, decision_limit=2)
    assert restarted.decision("0") is None
    assert restarted.decision("1") and restarted.decision("2")


def test_corrupted_policy_fails_closed(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = ServiceState(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE policy_revisions SET sha256='corrupted'")
    with pytest.raises(ValueError, match="checksum"):
        store.current_policy()


def test_two_os_processes_cannot_overwrite_the_same_policy_revision(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = ServiceState(path)
    # Children use the same interpreter and import paths as this test process.
    code = '''import sys,json,pathlib
sys.path[:] = json.loads(sys.argv[1])
from fusion_compliance_loop.service_state import ServiceState,RevisionConflict
try:
    ServiceState(pathlib.Path(sys.argv[2])).replace_policy(sys.argv[3],1)
    print("committed")
except RevisionConflict:
    print("conflict")
'''
    children = [subprocess.Popen([sys.executable, "-c", code, json.dumps(sys.path), str(path), policy(version)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for version in ("2.0.a", "2.0.b")]
    try:
        results = [child.communicate(timeout=20) for child in children]
        assert all(child.returncode == 0 for child in children), results
        assert sorted(out.strip() for out, _ in results) == ["committed", "conflict"]
        assert store.current_policy().revision == 2
        assert len(store.policy_history()) == 2
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


def test_policy_change_rolls_back_if_audit_write_fails(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = ServiceState(path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER reject_audit BEFORE INSERT ON policy_audit BEGIN SELECT RAISE(ABORT, 'simulated audit failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.replace_policy(policy("2.0.0"), 1)
    assert store.current_policy().revision == 1
    assert len(store.policy_history()) == 1


def test_process_termination_before_commit_preserves_previous_state(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = ServiceState(path)
    code = """import sqlite3,sys,time
conn=sqlite3.connect(sys.argv[1])
conn.execute('BEGIN IMMEDIATE')
conn.execute("UPDATE policy_revisions SET sha256='uncommitted'")
print('transaction-open',flush=True)
sys.stdin.read(1)
"""
    child = subprocess.Popen([sys.executable, "-c", code, str(path)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "transaction-open"
    finally:
        child.kill()
        child.communicate(timeout=10)
    assert store.current_policy().revision == 1
    assert store.current_policy().public()["policy_version"] == "1.0.0"
