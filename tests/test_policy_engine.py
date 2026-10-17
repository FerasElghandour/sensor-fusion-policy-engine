from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain, PolicyAction
from fusion_compliance_loop.models import RadarDetection
from fusion_compliance_loop.policy_engine import PolicyEngine


def _radar(**overrides):
    defaults = dict(confidence_score=0.7)
    defaults.update(overrides)
    return RadarDetection(**defaults)


def test_confidential_unreleased_is_rejected():
    item = _radar(classification_level=ClassificationLevel.CONFIDENTIAL, release_permissions=[NetworkDomain.RESTRICTED_NET])
    engine = PolicyEngine()
    decision = engine.evaluate(item, NetworkDomain.OPEN)
    assert decision.action == PolicyAction.REJECT
    assert decision.rule_name == "FORBIDDEN_DOMAIN"


def test_restricted_unreleased_is_segregated_not_rejected():
    item = _radar(
        classification_level=ClassificationLevel.RESTRICTED,
        release_permissions=[NetworkDomain.RESTRICTED_NET],
        raw_signal_signature="sig-1",
    )
    engine = PolicyEngine()
    decision = engine.evaluate(item, NetworkDomain.OPEN)
    assert decision.action == PolicyAction.SEGREGATE
    assert decision.rule_name == "RESTRICTED_CROSS_DOMAIN"
    assert "raw_signal_signature" in decision.blocked_fields


def test_sensitive_with_permissions_declared_elsewhere_is_restricted():
    item = _radar(classification_level=ClassificationLevel.SENSITIVE, release_permissions=[NetworkDomain.INTERNAL])
    engine = PolicyEngine()
    decision = engine.evaluate(item, NetworkDomain.OPEN)
    assert decision.action == PolicyAction.RESTRICT
    assert decision.rule_name == "SENSITIVE_MASKING"


def test_misclassified_field_requires_review():
    item = _radar(classification_level=ClassificationLevel.PUBLIC, release_permissions=[NetworkDomain.OPEN], raw_signal_signature="sig-1")
    engine = PolicyEngine()
    decision = engine.evaluate(item, NetworkDomain.OPEN)
    assert decision.action == PolicyAction.REQUIRE_REVIEW
    assert decision.rule_name == "MISCLASSIFIED_FIELD"


def test_missing_release_permissions_requires_review():
    item = _radar(classification_level=ClassificationLevel.SENSITIVE, release_permissions=[])
    engine = PolicyEngine()
    decision = engine.evaluate(item, NetworkDomain.OPEN)
    assert decision.action == PolicyAction.REQUIRE_REVIEW
    assert decision.rule_name == "MISSING_RELEASE_PERMISSION"


def test_public_released_data_is_permitted():
    item = _radar(classification_level=ClassificationLevel.PUBLIC, release_permissions=[NetworkDomain.OPEN])
    engine = PolicyEngine()
    decision = engine.evaluate(item, NetworkDomain.OPEN)
    assert decision.action == PolicyAction.PERMIT
    assert decision.rule_name == "DEFAULT_PERMIT"


def test_every_decision_names_its_rule():
    engine = PolicyEngine()
    items = [
        _radar(classification_level=ClassificationLevel.CONFIDENTIAL, release_permissions=[]),
        _radar(classification_level=ClassificationLevel.RESTRICTED, release_permissions=[]),
        _radar(classification_level=ClassificationLevel.PUBLIC, release_permissions=[NetworkDomain.OPEN]),
    ]
    for item in items:
        decision = engine.evaluate(item, NetworkDomain.OPEN)
        assert decision.rule_name


def test_apply_blocks_field_values_for_segregate():
    item = _radar(
        classification_level=ClassificationLevel.RESTRICTED,
        release_permissions=[],
        raw_signal_signature="sig-secret",
    )
    engine = PolicyEngine()
    filtered, decision = engine.apply(item, NetworkDomain.OPEN)
    assert filtered.raw_signal_signature is None
    assert item.raw_signal_signature == "sig-secret"  # original untouched
