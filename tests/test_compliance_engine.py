from fusion_compliance_loop.ai_compliance_risk import ComplianceRiskModel
from fusion_compliance_loop.audit_log_exporter import read_audit_log
from fusion_compliance_loop.compliance_engine import ComplianceDisposition, ComplianceEngine
from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain
from fusion_compliance_loop.policy_engine import PolicyEngine
from fusion_compliance_loop.provenance_recorder import ProvenanceRecorder
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


def _engine(use_ai_risk=True):
    return ComplianceEngine(policy_engine=PolicyEngine(), provenance=ProvenanceRecorder(), use_ai_risk=use_ai_risk)


# 5. Both camera and radar inputs are independently checked.
def test_camera_data_can_be_blocked_independently():
    engine = _engine()
    camera = make_camera_detection(
        classification_level=ClassificationLevel.PROTECTED_B,
        release_permissions=[NetworkDomain.CANADA_PROTECTED],
        network_domain=NetworkDomain.CANADA_PROTECTED,
        facial_recognition_signature="sig-camera-secret",
    )
    disposition = engine.inspect(camera, NetworkDomain.COALITION_UNCLASSIFIED)
    assert disposition.policy_decision.action.value == "SEGREGATE"
    assert disposition.filtered_item.facial_recognition_signature is None


def test_radar_data_can_be_blocked_independently():
    engine = _engine()
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)
    disposition = engine.inspect(pool[0], NetworkDomain.OPEN)  # RESTRICTED, not released for OPEN
    assert disposition.policy_decision.action.value == "SEGREGATE"
    assert disposition.filtered_item.raw_signal_signature is None


def test_one_modality_permitted_while_other_segregated():
    engine = _engine()
    camera = make_camera_detection()  # PUBLIC, fully released -> PERMIT
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)  # pool[0] RESTRICTED -> SEGREGATE

    camera_disposition = engine.inspect(camera, NetworkDomain.OPEN)
    radar_disposition = engine.inspect(pool[0], NetworkDomain.OPEN)

    assert camera_disposition.policy_decision.action.value == "PERMIT"
    assert radar_disposition.policy_decision.action.value == "SEGREGATE"
    assert camera_disposition.approved and radar_disposition.approved


def test_restricted_camera_fields_never_enter_fusion():
    engine = _engine()
    camera = make_camera_detection(
        classification_level=ClassificationLevel.RESTRICTED,
        release_permissions=[NetworkDomain.RESTRICTED_NET],
        network_domain=NetworkDomain.OPEN,
        facial_recognition_signature="sig-camera-secret",
    )
    disposition = engine.inspect(camera, NetworkDomain.OPEN)
    assert disposition.filtered_item.facial_recognition_signature is None
    assert "facial_recognition_signature" in disposition.policy_decision.blocked_fields


def test_restricted_radar_fields_never_enter_fusion():
    engine = _engine()
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)
    disposition = engine.inspect(pool[0], NetworkDomain.OPEN)
    assert disposition.filtered_item.raw_signal_signature is None


# 11. Every ingested item receives a compliance disposition.
def test_every_inspected_item_receives_a_disposition_with_required_fields():
    engine = _engine()
    camera = make_camera_detection()
    disposition = engine.inspect(camera, NetworkDomain.OPEN)
    assert isinstance(disposition, ComplianceDisposition)
    assert disposition.compliance_decision_id
    assert disposition.item_id == camera.id
    assert disposition.policy_decision.policy_id
    assert disposition.policy_decision.policy_version


# 2. AI output is consumed by the compliance decision process (not an unused signal).
def test_ai_risk_escalates_an_otherwise_default_permit_item():
    policy_engine = PolicyEngine()
    engine = ComplianceEngine(policy_engine=policy_engine, provenance=ProvenanceRecorder(), use_ai_risk=True)

    camera = make_camera_detection(
        classification_marking_present=False,
        domain_of_origin_marking_present=False,
        release_authority_marking_present=False,
    )
    camera.transformation_history = ["manual:downgrade_requested", "manual:reclassified", "manual:reclassified_again"]

    disposition = engine.inspect(camera, NetworkDomain.OPEN)
    # A well-formed item like this would DEFAULT_PERMIT with no AI signal;
    # the deliberately suspicious metadata above should push the AI risk
    # score high enough for AI_HIGH_RISK_REVIEW to fire instead.
    assert disposition.ai_risk.risk_probability >= 0.85, disposition.ai_risk.risk_probability
    assert disposition.policy_decision.rule_name == "AI_HIGH_RISK_REVIEW"
    assert disposition.policy_decision.action.value == "REQUIRE_REVIEW"
    assert disposition.ai_risk.risk_categories  # the signal is visible, not just a dashboard number


# 3. AI cannot directly authorize data release.
# 16. AI false positives cannot override deterministic permissions.
def test_ai_false_positive_cannot_loosen_a_deterministic_reject():
    """Feed a maximal (1.0) risk score into an item that deterministically
    REJECTs — the AI being "very confident" this is fine must not matter;
    only the deterministic FORBIDDEN_DOMAIN rule (higher priority than the
    AI rule) may decide this."""
    policy_engine = PolicyEngine()
    camera = make_camera_detection()  # irrelevant to this test
    confidential_item = make_radar_pool(camera.timestamp, camera.location, seed=1)[0]
    confidential_item.classification_level = ClassificationLevel.CONFIDENTIAL
    confidential_item.release_permissions = [NetworkDomain.RESTRICTED_NET]

    decision_no_ai = policy_engine.evaluate(confidential_item, NetworkDomain.OPEN, ai_risk_score=None)
    decision_max_ai = policy_engine.evaluate(confidential_item, NetworkDomain.OPEN, ai_risk_score=1.0)

    assert decision_no_ai.action.value == "REJECT"
    assert decision_max_ai.action.value == "REJECT"
    assert decision_no_ai.rule_name == decision_max_ai.rule_name == "FORBIDDEN_DOMAIN"


# 4. Deterministic policy remains final authority.
# 17. AI false negatives cannot bypass mandatory policy rules.
def test_ai_false_negative_cannot_bypass_mandatory_rule():
    """Even if the AI risk score is 0.0 (a total false negative — it saw
    nothing wrong), an item that deterministically violates a higher-
    priority rule is still blocked exactly the same."""
    policy_engine = PolicyEngine()
    camera = make_camera_detection()
    restricted_item = make_radar_pool(camera.timestamp, camera.location, seed=1)[0]

    decision_zero_ai = policy_engine.evaluate(restricted_item, NetworkDomain.OPEN, ai_risk_score=0.0)
    decision_no_ai = policy_engine.evaluate(restricted_item, NetworkDomain.OPEN, ai_risk_score=None)

    assert decision_zero_ai.rule_name == decision_no_ai.rule_name == "RESTRICTED_CROSS_DOMAIN"
    assert decision_zero_ai.action.value == "SEGREGATE"


# 13. Every decision has a plain-English explanation.
def test_disposition_explanation_is_plain_english():
    engine = _engine()
    camera = make_camera_detection()
    disposition = engine.inspect(camera, NetworkDomain.OPEN)
    assert disposition.policy_decision.explanation
    assert disposition.policy_decision.explanation[0].isupper()
    assert disposition.ai_risk.explanation


# 14. Every decision is exported into the audit record.
def test_compliance_decision_is_exported_into_audit_record():
    provenance = ProvenanceRecorder()
    engine = ComplianceEngine(policy_engine=PolicyEngine(), provenance=provenance, use_ai_risk=True)
    camera = make_camera_detection()
    engine.inspect(camera, NetworkDomain.OPEN)

    log = read_audit_log(provenance.conn)
    event_types = {row["event_type"] for row in log}
    assert "COMPLIANCE_DECISION" in event_types


def test_use_ai_risk_false_disables_ai_but_keeps_deterministic_enforcement():
    engine = _engine(use_ai_risk=False)
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)
    disposition = engine.inspect(pool[0], NetworkDomain.OPEN)
    assert disposition.ai_risk.risk_probability == 0.0
    assert disposition.policy_decision.rule_name == "RESTRICTED_CROSS_DOMAIN"
