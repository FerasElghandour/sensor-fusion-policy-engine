from fusion_compliance_loop.compliance_engine import ComplianceEngine
from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain
from fusion_compliance_loop.policy_engine import PolicyEngine
from fusion_compliance_loop.provenance_recorder import ProvenanceRecorder
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection


def _engine():
    return ComplianceEngine(policy_engine=PolicyEngine(), provenance=ProvenanceRecorder(), use_ai_risk=False)


# 6. Protected B exists as an explicit classification.
def test_protected_b_is_an_explicit_classification_level():
    assert ClassificationLevel.PROTECTED_B.value == "protected_b"
    assert ClassificationLevel.PROTECTED_B != ClassificationLevel.SENSITIVE
    assert ClassificationLevel.PROTECTED_B != ClassificationLevel.RESTRICTED
    assert ClassificationLevel.PROTECTED_B != ClassificationLevel.CONFIDENTIAL


def test_two_explicit_synthetic_network_domains_exist():
    assert NetworkDomain.CANADA_PROTECTED.value == "canada_protected"
    assert NetworkDomain.COALITION_UNCLASSIFIED.value == "coalition_unclassified"


# 7. Protected B remains inside authorized network domains.
def test_protected_b_permitted_within_canada_protected_when_released():
    engine = _engine()
    item = make_camera_detection(
        classification_level=ClassificationLevel.PROTECTED_B,
        release_permissions=[NetworkDomain.CANADA_PROTECTED],
        network_domain=NetworkDomain.CANADA_PROTECTED,
    )
    disposition = engine.inspect(item, NetworkDomain.CANADA_PROTECTED)
    assert disposition.policy_decision.action.value == "PERMIT"
    assert disposition.approved


# 8. Protected B cannot enter unauthorized network domains.
def test_protected_b_blocked_from_coalition_unclassified_without_release_authority():
    engine = _engine()
    item = make_camera_detection(
        classification_level=ClassificationLevel.PROTECTED_B,
        release_permissions=[NetworkDomain.CANADA_PROTECTED],
        network_domain=NetworkDomain.CANADA_PROTECTED,
        facial_recognition_signature="sig-protected",
    )
    disposition = engine.inspect(item, NetworkDomain.COALITION_UNCLASSIFIED)
    assert disposition.policy_decision.rule_name == "PROTECTED_B_CROSS_DOMAIN"
    assert disposition.policy_decision.action.value == "SEGREGATE"
    assert disposition.filtered_item.facial_recognition_signature is None
    # Approved non-sensitive metadata still crosses:
    assert disposition.filtered_item.confidence_score == item.confidence_score


def test_approved_non_sensitive_metadata_crosses_domains_when_explicitly_permitted():
    engine = _engine()
    item = make_camera_detection(
        classification_level=ClassificationLevel.PROTECTED_B,
        release_permissions=[NetworkDomain.CANADA_PROTECTED, NetworkDomain.COALITION_UNCLASSIFIED],
        network_domain=NetworkDomain.CANADA_PROTECTED,
    )
    disposition = engine.inspect(item, NetworkDomain.COALITION_UNCLASSIFIED)
    assert disposition.policy_decision.action.value == "PERMIT"


def test_unauthorized_downgrade_attempt_is_rejected_not_permitted():
    """No downgrade_authorized_by on file -> falls through to the ordinary
    segregation rule, never to a full PERMIT/DOWNGRADE."""
    engine = _engine()
    item = make_camera_detection(
        classification_level=ClassificationLevel.PROTECTED_B,
        release_permissions=[NetworkDomain.CANADA_PROTECTED],
        network_domain=NetworkDomain.CANADA_PROTECTED,
        facial_recognition_signature="sig-protected",
    )
    disposition = engine.inspect(item, NetworkDomain.COALITION_UNCLASSIFIED)
    assert disposition.policy_decision.action.value != "DOWNGRADE"
    assert disposition.policy_decision.action.value == "SEGREGATE"


def test_authorized_downgrade_requires_specific_rule_and_accountability_record():
    engine = _engine()
    item = make_camera_detection(
        classification_level=ClassificationLevel.PROTECTED_B,
        release_permissions=[NetworkDomain.CANADA_PROTECTED],
        network_domain=NetworkDomain.CANADA_PROTECTED,
        facial_recognition_signature="sig-protected",
        downgrade_authorized_by="ops-officer-42",
    )
    disposition = engine.inspect(item, NetworkDomain.COALITION_UNCLASSIFIED)
    assert disposition.policy_decision.rule_name == "AUTHORIZED_PROTECTED_B_DOWNGRADE"
    assert disposition.policy_decision.action.value == "DOWNGRADE"
    assert disposition.filtered_item.facial_recognition_signature is None  # still stripped, only metadata crosses
    assert "ops-officer-42" in disposition.policy_decision.explanation  # accountability record


def test_downgrade_action_is_a_distinct_policy_action():
    from fusion_compliance_loop.enums import PolicyAction

    assert PolicyAction.DOWNGRADE.value == "DOWNGRADE"
    assert PolicyAction.DOWNGRADE != PolicyAction.RESTRICT
