"""Tests for the v0.2 external, machine-readable policy loader."""

import pytest
import yaml

from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain
from fusion_compliance_loop.models import RadarDetection
from fusion_compliance_loop.policy_engine import DEFAULT_POLICY_PATH, PolicyEngine, PolicyLoadError
from fusion_compliance_loop.policy_schema import PolicyFile


def _valid_policy_dict():
    return yaml.safe_load(DEFAULT_POLICY_PATH.read_text())


def test_default_policy_loads_and_exposes_id_and_version():
    engine = PolicyEngine()
    assert engine.policy_id == "fusion-compliance-baseline"
    assert engine.policy_version
    # 6 original rules + AUTHORIZED_PROTECTED_B_DOWNGRADE, PROTECTED_B_CROSS_DOMAIN,
    # AI_HIGH_RISK_REVIEW (v0.3 compliance-risk audit).
    assert engine.rule_count == 9


def test_policy_loads_from_yaml_without_code_changes(tmp_path):
    custom = _valid_policy_dict()
    custom["policy_id"] = "custom-test-policy"
    custom["policy_version"] = "9.9.9"
    path = tmp_path / "custom_policy.yaml"
    path.write_text(yaml.safe_dump(custom))

    engine = PolicyEngine(policy_path=path)
    assert engine.policy_id == "custom-test-policy"
    assert engine.policy_version == "9.9.9"


def test_every_decision_carries_policy_id_version_rule_and_timestamp():
    engine = PolicyEngine()
    item = RadarDetection(confidence_score=0.7, classification_level=ClassificationLevel.PUBLIC, release_permissions=[NetworkDomain.OPEN])
    decision = engine.evaluate(item, NetworkDomain.OPEN)
    assert decision.policy_id == engine.policy_id
    assert decision.policy_version == engine.policy_version
    assert decision.rule_version
    assert decision.rule_name
    assert decision.timestamp is not None
    assert decision.reason == decision.explanation


def test_invalid_policy_reload_is_rejected_and_active_policy_survives():
    engine = PolicyEngine()
    original_version = engine.policy_version

    with pytest.raises(PolicyLoadError):
        engine.reload_from_text("not: [valid, policy, - structure")  # bad YAML

    with pytest.raises(PolicyLoadError):
        engine.reload_from_text(yaml.safe_dump({"policy_id": "x", "policy_version": "1.0", "rules": []}))  # no rules

    assert engine.policy_version == original_version
    # Engine must still work normally after the rejected reloads.
    item = RadarDetection(confidence_score=0.5, classification_level=ClassificationLevel.PUBLIC, release_permissions=[NetworkDomain.OPEN])
    decision = engine.evaluate(item, NetworkDomain.OPEN)
    assert decision.rule_name == "DEFAULT_PERMIT"


def test_policy_without_catchall_rule_is_rejected():
    from fusion_compliance_loop.policy_engine import load_policy_text

    bad = _valid_policy_dict()
    bad["rules"] = [r for r in bad["rules"] if r["rule_id"] != "DEFAULT_PERMIT"]
    with pytest.raises(PolicyLoadError):
        load_policy_text(yaml.safe_dump(bad))


def test_valid_reload_applies_live_no_restart():
    engine = PolicyEngine()
    updated = _valid_policy_dict()
    updated["policy_version"] = "2.0.0"
    engine.reload_from_text(yaml.safe_dump(updated))
    assert engine.policy_version == "2.0.0"
    # Rules still function post-reload.
    item = RadarDetection(confidence_score=0.7, classification_level=ClassificationLevel.CONFIDENTIAL, release_permissions=[])
    decision = engine.evaluate(item, NetworkDomain.OPEN)
    assert decision.action.value == "REJECT"
    assert decision.policy_version == "2.0.0"


def test_required_metadata_gates_a_rule(tmp_path):
    """A rule with required_metadata should only match once every listed
    field is present — proves the schema field is functionally enforced,
    not just accepted and ignored."""
    policy = _valid_policy_dict()
    policy["rules"].insert(
        0,
        {
            "rule_id": "REQUIRES_DIRECTION",
            "rule_version": "1.0.0",
            "rule_priority": 5,
            "effective_date": "2026-01-01",
            "classification_level": ["public"],
            "required_metadata": ["direction_deg"],
            "enforcement_action": "RESTRICT",
            "restricted_fields": [],
            "permitted_fields": [],
        },
    )
    path = tmp_path / "requires_direction_policy.yaml"
    path.write_text(yaml.safe_dump(policy))
    engine = PolicyEngine(policy_path=path)

    with_direction = RadarDetection(confidence_score=0.5, classification_level=ClassificationLevel.PUBLIC, release_permissions=[NetworkDomain.OPEN], direction_deg=90.0)
    without_direction = RadarDetection(confidence_score=0.5, classification_level=ClassificationLevel.PUBLIC, release_permissions=[NetworkDomain.OPEN])

    assert engine.evaluate(with_direction, NetworkDomain.OPEN).rule_name == "REQUIRES_DIRECTION"
    assert engine.evaluate(without_direction, NetworkDomain.OPEN).rule_name == "DEFAULT_PERMIT"


def test_policy_file_schema_validates_all_required_fields():
    policy = PolicyFile.model_validate(_valid_policy_dict())
    for rule in policy.rules:
        assert rule.rule_id
        assert rule.rule_version
        assert isinstance(rule.rule_priority, int)
        assert rule.effective_date
        assert rule.enforcement_action
