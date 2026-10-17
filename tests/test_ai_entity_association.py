from datetime import datetime, timezone

from fusion_compliance_loop.ai_entity_association import (
    EntityAssociationModel,
    ai_rank_candidates,
    extract_features,
    get_default_model,
)
from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain
from fusion_compliance_loop.fusion_engine import FusionEngine
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


def test_model_trains_and_beats_a_coin_flip():
    model = EntityAssociationModel().train(n_samples=2000, seed=1)
    assert model.trained
    assert model.holdout_accuracy > 0.75  # meaningfully better than random guessing


def test_extract_features_returns_all_named_inputs():
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)
    features = extract_features(camera, pool[0])
    for key in (
        "time_diff_s",
        "distance_diff_m",
        "direction_diff_deg",
        "speed_plausibility_diff",
        "sensor_confidence",
        "object_type_similarity",
        "data_completeness",
        "sensor_reliability",
    ):
        assert key in features


def test_prediction_has_probability_label_and_explanation():
    model = get_default_model()
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)
    features = extract_features(camera, pool[0])
    prediction = model.predict(features)
    assert 0.0 <= prediction.match_probability <= 1.0
    assert isinstance(prediction.predicted_match, bool)
    assert prediction.explanation
    assert all(isinstance(line, str) and line for line in prediction.explanation)


def test_ai_rank_candidates_orders_by_probability_descending():
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)
    ranked = ai_rank_candidates(camera, pool)
    probs = [p.match_probability for _radar, p, _f in ranked]
    assert probs == sorted(probs, reverse=True)


def test_missing_data_is_scored_as_a_gap_not_imputed_favorably():
    camera = make_camera_detection()
    pool = make_radar_pool(datetime.now(timezone.utc), camera.location, seed=1)
    camera.timestamp = None
    features = extract_features(camera, pool[0])
    assert features["time_diff_s"] == 999.0


def test_ai_assisted_fusion_still_enforces_policy_and_never_leaks_restricted_field():
    """The AI only recommends a candidate — policy_engine.apply() must still
    run on whatever it recommends, and a RESTRICTED field must still be
    blocked exactly as it is on the deterministic path."""
    camera = make_camera_detection()
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)

    result = engine.run(
        camera,
        lambda: make_radar_pool(camera.timestamp, camera.location, seed=1),
        use_ai_association=True,
    )
    assert "RESTRICTED_CROSS_DOMAIN:SEGREGATE" in result.applied_policy_rules
    assert "raw_signal_signature" in result.blocked_fields
    assert result.candidates_considered
    assert result.candidates_considered[0].rationale.startswith("AI model:")


def test_ai_assisted_fusion_rejects_confidential_data_same_as_deterministic_path():
    camera = make_camera_detection()
    engine = FusionEngine(network_domain=NetworkDomain.OPEN)

    def confidential_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=8)
        pool[0].classification_level = ClassificationLevel.CONFIDENTIAL
        pool[0].release_permissions = [NetworkDomain.RESTRICTED_NET]
        return pool

    result = engine.run(camera, confidential_pool, use_ai_association=True)
    assert result.contributing_data_ids == [camera.id]
    assert "*" in result.blocked_fields
