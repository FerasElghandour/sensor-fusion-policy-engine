"""Integration-level proof, through the full FusionEngine, of the v0.3
acceptance targets (essential submission blockers 1-3, application/
MINIMUM_CODE_CHANGES.md). Complements the unit-level tests in
test_ai_compliance_risk.py, test_compliance_engine.py,
test_downstream_fusion.py, and test_protected_b.py, which each also carry
their own copy of the specific numbered requirement they satisfy."""

from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain
from fusion_compliance_loop.fusion_engine import FusionEngine
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


# 5. Both camera and radar inputs are independently checked (end to end).
def test_camera_reject_stops_before_radar_is_even_requested():
    """CONFIDENTIAL (not RESTRICTED) is used here because RESTRICTED
    resolves to SEGREGATE (partial data still proceeds) — a true REJECT
    requires the FORBIDDEN_DOMAIN rule."""
    camera = make_camera_detection(
        classification_level=ClassificationLevel.CONFIDENTIAL,
        release_permissions=[NetworkDomain.RESTRICTED_NET],
    )
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))

    assert not result.camera_approved
    assert result.camera_policy_rule.startswith("FORBIDDEN_DOMAIN")
    assert result.contributing_data_ids == []  # camera blocked -> nothing reaches fusion
    assert result.radar_dispositions == []  # radar was never even requested


def test_camera_segregated_still_contributes_its_permitted_fields():
    """RESTRICTED camera data is SEGREGATED, not REJECTED — its sensitive
    field is stripped but the rest of the item still flows through."""
    camera = make_camera_detection(
        classification_level=ClassificationLevel.RESTRICTED,
        release_permissions=[NetworkDomain.RESTRICTED_NET],
        facial_recognition_signature="sig-camera-secret",
    )
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))

    assert result.camera_approved
    assert result.camera_policy_rule.startswith("RESTRICTED_CROSS_DOMAIN")
    assert "facial_recognition_signature" in result.camera_blocked_fields
    assert result.contributing_data_ids  # camera (and possibly radar) still contribute


def test_camera_permitted_while_top_radar_candidate_is_segregated():
    camera = make_camera_detection()  # PUBLIC, always PERMIT
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))

    assert result.camera_approved
    assert result.camera_policy_rule.startswith("DEFAULT_PERMIT")
    assert "RESTRICTED_CROSS_DOMAIN:SEGREGATE" in result.applied_policy_rules
    # Every radar candidate that reached the pool got its own disposition:
    assert len(result.radar_dispositions) == 3
    assert all(d["policy_id"] for d in result.radar_dispositions)
    assert all(d["compliance_decision_id"] for d in result.radar_dispositions)


# 11. Every ingested item receives a compliance disposition.
def test_every_radar_candidate_receives_its_own_disposition_not_just_the_winner():
    camera = make_camera_detection()
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))
    actions = {d["action"] for d in result.radar_dispositions}
    # pool[0] is RESTRICTED+unreleased (SEGREGATE); pool[1]/pool[2] are PUBLIC+released (PERMIT).
    assert actions == {"SEGREGATE", "PERMIT"}


# 10. Every enforcement action names its policy ID and version (camera side too).
def test_camera_disposition_names_policy_id_and_version():
    camera = make_camera_detection()
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))
    assert result.camera_compliance_decision_id
    for d in result.radar_dispositions:
        assert d["policy_id"] == engine.policy.policy_id
        assert d["policy_version"] == engine.policy.policy_version


# 18. All evidence-seeking and fusion loops terminate (regression, new engine).
def test_evidence_and_fusion_loop_terminates_with_new_compliance_gate():
    camera = make_camera_detection()
    engine = FusionEngine(network_domain=NetworkDomain.OPEN, max_sensor_requests=1)
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))
    assert engine.planner.requests_made <= engine.planner.max_requests
    assert result.explanation


# 12. Every downstream output traces to original inputs (through the full engine).
def test_full_engine_output_still_traces_to_original_inputs():
    camera = make_camera_detection()
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))
    chain = engine.provenance.trace_to_inputs(result.conclusion_id)
    assert camera.id in chain
    assert len(result.contributing_data_ids) == 2
    for cid in result.contributing_data_ids:
        assert cid in chain


# 13. Every decision has a plain-English explanation (camera-blocked path too).
def test_camera_blocked_explanation_is_plain_english():
    camera = make_camera_detection(
        classification_level=ClassificationLevel.CONFIDENTIAL,
        release_permissions=[NetworkDomain.RESTRICTED_NET],
    )
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))
    assert not result.camera_approved
    assert result.explanation
    assert result.explanation[0].isupper()


# model-based association still works with the new compliance gate.
def test_ai_assisted_run_still_gates_both_modalities():
    camera = make_camera_detection()
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)
    result = engine.run(
        camera,
        lambda: make_radar_pool(camera.timestamp, camera.location, seed=1),
        use_ai_association=True,
    )
    assert result.camera_approved
    assert len(result.radar_dispositions) == 3
