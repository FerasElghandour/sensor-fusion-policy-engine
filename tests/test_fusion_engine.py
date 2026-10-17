from fusion_compliance_loop.enums import NetworkDomain
from fusion_compliance_loop.fusion_engine import FusionEngine
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


def test_scenario_1_end_to_end():
    """Camera at 55% confidence -> requests radar -> best match found ->
    RESTRICTED field segregated -> confidence rises using permitted evidence only."""
    camera = make_camera_detection(confidence=0.55)
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)

    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))

    assert result.confidence_before == 0.55
    assert result.confidence_after > result.confidence_before
    # Camera and radar are independent (radar wasn't derived from the camera
    # frame), so this must compound via noisy-OR, not just take the max.
    assert result.confidence_after == 0.919
    assert any("Requested radar" in line for line in result.requested_evidence)
    assert "RESTRICTED_CROSS_DOMAIN:SEGREGATE" in result.applied_policy_rules
    assert "raw_signal_signature" in result.blocked_fields
    assert result.candidates_considered  # three radar candidates were ranked
    assert len(result.candidates_considered) == 3
    assert result.explanation


def test_rejected_radar_never_contributes():
    from fusion_compliance_loop.enums import ClassificationLevel

    camera = make_camera_detection()
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)

    def confidential_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=8)
        pool[0].classification_level = ClassificationLevel.CONFIDENTIAL
        pool[0].release_permissions = [NetworkDomain.RESTRICTED_NET]
        return pool

    result = engine.run(camera, confidential_pool)
    assert len(result.contributing_data_ids) == 1
    assert result.contributing_data_ids == [camera.id]
    assert result.confidence_after == result.confidence_before
