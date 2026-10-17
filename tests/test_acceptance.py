"""Acceptance tests mirroring the six criteria from the project brief."""

from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain
from fusion_compliance_loop.fusion_engine import FusionEngine
from fusion_compliance_loop.policy_engine import PolicyEngine
from fusion_compliance_loop.models import RadarDetection
from fusion_compliance_loop.scenarios import SCENARIOS
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


def test_every_fusion_output_traces_back_to_original_inputs():
    for scenario_fn in SCENARIOS:
        name, engine_or_planner, camera, result_or_outcomes = scenario_fn()
        if name == "repeated_evidence_seeking_loop":
            continue
        result = result_or_outcomes
        trace = engine_or_planner.provenance.trace_to_inputs(result.conclusion_id)
        assert camera.id in trace, f"{name}: camera input missing from provenance trace"


def test_every_policy_decision_names_its_rule():
    engine = PolicyEngine()
    samples = [
        RadarDetection(confidence_score=0.5, classification_level=ClassificationLevel.CONFIDENTIAL, release_permissions=[]),
        RadarDetection(confidence_score=0.5, classification_level=ClassificationLevel.RESTRICTED, release_permissions=[]),
        RadarDetection(confidence_score=0.5, classification_level=ClassificationLevel.SENSITIVE, release_permissions=[NetworkDomain.INTERNAL]),
        RadarDetection(confidence_score=0.5, classification_level=ClassificationLevel.PUBLIC, raw_signal_signature="x", release_permissions=[NetworkDomain.OPEN]),
        RadarDetection(confidence_score=0.5, classification_level=ClassificationLevel.SENSITIVE, release_permissions=[]),
        RadarDetection(confidence_score=0.5, classification_level=ClassificationLevel.PUBLIC, release_permissions=[NetworkDomain.OPEN]),
    ]
    for item in samples:
        decision = engine.evaluate(item, NetworkDomain.OPEN)
        assert decision.rule_name, "every policy decision must name the rule that produced it"


def test_forbidden_data_never_enters_fusion_result():
    camera = make_camera_detection()
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)

    def confidential_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=8)
        pool[0].classification_level = ClassificationLevel.CONFIDENTIAL
        pool[0].release_permissions = [NetworkDomain.RESTRICTED_NET]
        return pool

    rejected_radar = confidential_pool()[0]
    result = engine.run(camera, confidential_pool)

    assert rejected_radar.id not in result.contributing_data_ids
    assert "*" in result.blocked_fields


def test_confidence_does_not_increase_from_duplicated_dependent_evidence():
    camera = make_camera_detection(confidence=0.55)
    engine = FusionEngine()

    def derived_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=6)
        pool[0].parent_data_ids = [camera.id]  # derived from the same camera frame
        return pool

    result = engine.run(camera, derived_pool)
    best_radar_confidence = derived_pool()[0].confidence_score
    assert result.confidence_after == max(camera.confidence_score, best_radar_confidence)


def test_evidence_seeking_loop_stops_at_configured_limit():
    from fusion_compliance_loop.active_sensor_request_planner import SensorRequestPlanner

    planner = SensorRequestPlanner(max_requests=2)
    missing = ["speed_mps", "distance_m"]
    for _ in range(10):
        planner.request(missing)
    assert planner.requests_made == 2


def test_every_decision_is_understandable_in_plain_english():
    for scenario_fn in SCENARIOS:
        name, engine_or_planner, camera, result_or_outcomes = scenario_fn()
        if name == "repeated_evidence_seeking_loop":
            continue
        result = result_or_outcomes
        assert result.explanation and result.explanation[0].isupper()
        assert "." in result.explanation
