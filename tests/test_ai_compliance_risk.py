from fusion_compliance_loop.ai_compliance_risk import (
    ComplianceRiskModel,
    RISK_FEATURE_NAMES,
    extract_risk_features,
    generate_training_examples,
)
from fusion_compliance_loop.enums import NetworkDomain
from fusion_compliance_loop.models import ComplianceRiskAssessment
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


def test_model_trains_and_beats_a_coin_flip():
    model = ComplianceRiskModel().train()
    assert model.holdout_accuracy > 0.6


def test_extract_features_returns_all_named_inputs():
    camera = make_camera_detection()
    features = extract_risk_features(camera, {"raw_signal_signature": "restricted"}, NetworkDomain.OPEN)
    assert set(features) == set(RISK_FEATURE_NAMES)
    for value in features.values():
        assert 0.0 <= value <= 1.0


# 1. AI produces a compliance-relevant risk output.
def test_ai_produces_a_compliance_relevant_risk_output():
    camera = make_camera_detection()
    model = ComplianceRiskModel().train()
    assessment = model.assess(camera, {"raw_signal_signature": "restricted"}, NetworkDomain.OPEN)
    assert isinstance(assessment, ComplianceRiskAssessment)
    assert 0.0 <= assessment.risk_probability <= 1.0
    assert 0.0 <= assessment.confidence <= 1.0
    assert assessment.explanation
    assert isinstance(assessment.risk_categories, list)
    assert isinstance(assessment.contributing_factors, list)


def test_well_formed_item_scores_low_risk():
    """A clean, fully-marked, un-transformed item should not trip any risk
    category — this is the baseline that keeps the AI_HIGH_RISK_REVIEW rule
    from firing on ordinary, well-formed synthetic test data."""
    camera = make_camera_detection()
    model = ComplianceRiskModel().train()
    assessment = model.assess(camera, {"raw_signal_signature": "restricted"}, NetworkDomain.OPEN)
    assert assessment.risk_probability < 0.5
    assert assessment.risk_categories == []


def test_missing_metadata_markings_raise_risk_categories():
    camera = make_camera_detection(
        classification_marking_present=False,
        domain_of_origin_marking_present=False,
        release_authority_marking_present=False,
    )
    features = extract_risk_features(camera, {}, NetworkDomain.OPEN)
    assert features["missing_classification_marking"] == 1.0
    assert features["missing_domain_of_origin"] == 1.0
    assert features["missing_release_authority"] == 1.0


def test_classification_field_mismatch_detected():
    pool = make_radar_pool(make_camera_detection().timestamp, make_camera_detection().location, seed=1)
    item = pool[1]  # PUBLIC, no raw_signal_signature by default
    item.classification_level = item.classification_level  # keep PUBLIC
    item.raw_signal_signature = "sig-hidden"
    features = extract_risk_features(item, {"raw_signal_signature": "restricted"}, NetworkDomain.OPEN)
    assert features["classification_field_mismatch"] == 1.0


def test_suspicious_downgrade_flagged_only_when_unauthorized():
    camera = make_camera_detection()
    camera.transformation_history = ["manual:downgrade_requested"]
    features_unauthorized = extract_risk_features(camera, {}, NetworkDomain.OPEN)
    assert features_unauthorized["suspicious_classification_downgrade"] == 1.0

    camera.downgrade_authorized_by = "ops-officer-1"
    features_authorized = extract_risk_features(camera, {}, NetworkDomain.OPEN)
    assert features_authorized["suspicious_classification_downgrade"] == 0.0


def test_source_destination_domain_conflict_detected():
    camera = make_camera_detection(network_domain=NetworkDomain.CANADA_PROTECTED, release_permissions=[NetworkDomain.CANADA_PROTECTED])
    features = extract_risk_features(camera, {}, target_domain=NetworkDomain.COALITION_UNCLASSIFIED)
    assert features["source_destination_domain_conflict"] == 1.0


def test_restricted_field_hidden_in_transformed_record_detected():
    camera = make_camera_detection()
    camera.facial_recognition_signature = "sig-smuggled"
    camera.transformation_history = ["some:prior_transform"]
    features = extract_risk_features(camera, {}, NetworkDomain.OPEN)
    assert features["restricted_field_pattern_in_transformed_record"] == 1.0


def test_generate_training_examples_shape():
    X, y = generate_training_examples(n=200, seed=1)
    assert X.shape == (200, len(RISK_FEATURE_NAMES))
    assert set(y.tolist()) <= {0.0, 1.0}


# 16. AI false positives cannot override deterministic permissions.
# 17. AI false negatives cannot bypass mandatory policy rules.
# (Structural check here; end-to-end proof lives in test_compliance_engine.py.)
def test_risk_assessment_has_no_enforcement_action_field():
    """The AI's output type structurally cannot carry an enforcement action
    — there is no field for one. It can only ever influence which *rule*
    becomes eligible to match (via requires_ai_risk_at_least), never decide
    the outcome directly."""
    fields = ComplianceRiskAssessment.model_fields
    assert "action" not in fields
    assert "enforcement_action" not in fields
