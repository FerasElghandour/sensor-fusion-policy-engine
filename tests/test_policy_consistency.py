import json
import pytest
import yaml
from fusion_compliance_loop.compliance_engine import ComplianceEngine
from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain
from fusion_compliance_loop.fusion_engine import FusionEngine
from fusion_compliance_loop.policy_engine import DEFAULT_POLICY_PATH, PolicyEngine, PolicyLoadError
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


def test_reload_during_mission_does_not_mix_policy_versions():
    shared = PolicyEngine()
    engine = FusionEngine(policy_engine=shared, use_ai_risk=False)
    camera = make_camera_detection()

    def pool_during_reload():
        changed = yaml.safe_load(DEFAULT_POLICY_PATH.read_text())
        changed["policy_version"] = "2.0.0"
        shared.reload_from_text(yaml.safe_dump(changed))
        return make_radar_pool(camera.timestamp, camera.location, seed=1)

    try:
        result = engine.run(camera, pool_during_reload)
        assert result.camera_policy_version == "1.0.0"
        assert result.radar_dispositions
        assert {r["policy_version"] for r in result.radar_dispositions} == {"1.0.0"}
        assert FusionEngine(policy_engine=shared).policy.policy_version == "2.0.0"
    finally:
        engine.provenance.conn.close()


def test_policy_property_cannot_mutate_active_configuration():
    engine = PolicyEngine()
    external = engine.policy
    external.policy_version = "changed"
    external.rules.clear()
    assert engine.policy_version == "1.0.0" and engine.rule_count == 9


@pytest.mark.parametrize("modification", ["unknown", "threshold", "future_catchall", "conditional_catchall"])
def test_malformed_policy_cannot_silently_disable_enforcement(modification):
    data = yaml.safe_load(DEFAULT_POLICY_PATH.read_text())
    if modification == "unknown":
        data["rules"][0]["enforcment_action"] = "REJECT"
    elif modification == "threshold":
        data["rules"][0]["requires_ai_risk_at_least"] = 2
    else:
        data["rules"] = [r for r in data["rules"] if r["rule_id"] == "DEFAULT_PERMIT"]
        if modification == "future_catchall":
            data["rules"][0]["effective_date"] = "2999-01-01"
        else:
            data["rules"][0]["required_metadata"] = ["direction_deg"]
    with pytest.raises(PolicyLoadError):
        PolicyEngine.from_text(yaml.safe_dump(data))


@pytest.mark.parametrize("rejected", [False, True])
def test_restricted_values_never_enter_provenance_sql_even_temporarily(rejected):
    marker = "synthetic-sensitive-marker-for-regression"
    camera = make_camera_detection(facial_recognition_signature=marker,
                                  classification_level=ClassificationLevel.CONFIDENTIAL if rejected else ClassificationLevel.RESTRICTED,
                                  release_permissions=[NetworkDomain.RESTRICTED_NET])
    engine = ComplianceEngine(use_ai_risk=False)
    statements = []
    engine.provenance.conn.set_trace_callback(statements.append)
    try:
        disposition = engine.inspect(camera, NetworkDomain.OPEN)
        assert disposition.approved is not rejected
        payload = engine.provenance.conn.execute("SELECT payload FROM provenance WHERE id=?", (camera.id,)).fetchone()[0]
        assert marker not in payload
        assert marker not in "\n".join(statements)
        if rejected:
            assert json.loads(payload) == {"id": camera.id, "rejected": True}
    finally:
        engine.provenance.conn.close()


def test_aliases_and_oversized_policies_are_rejected_before_validation():
    with pytest.raises(PolicyLoadError, match="aliases"):
        PolicyEngine.from_text("policy_id: &name example\npolicy_version: *name\nrules: []")
    with pytest.raises(PolicyLoadError, match="60000"):
        PolicyEngine.from_text("x" * 60001)


def test_canonical_json_and_yaml_have_the_same_policy_behavior():
    original = PolicyEngine()
    restored = PolicyEngine.from_text(original.policy.model_dump_json())
    camera = make_camera_detection()
    a = original.evaluate(camera, NetworkDomain.OPEN)
    b = restored.evaluate(camera, NetworkDomain.OPEN)
    assert (a.action, a.rule_name, a.policy_version) == (b.action, b.rule_name, b.policy_version)
