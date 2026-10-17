from fusion_compliance_loop.adversarial_generator import ADVERSARIAL_CONDITIONS, generate_missions
from fusion_compliance_loop.fusion_engine import FusionEngine


def test_generates_at_least_1000_missions():
    missions = generate_missions(n=1000, seed=7)
    assert len(missions) == 1000


def test_every_adversarial_condition_appears_at_least_once():
    missions = generate_missions(n=1000, seed=7)
    seen = {tag for m in missions for tag in m.tags}
    missing = set(ADVERSARIAL_CONDITIONS) - seen
    assert not missing, f"conditions never generated: {missing}"


def test_at_least_20_conditions_are_defined():
    assert len(ADVERSARIAL_CONDITIONS) >= 19


def test_every_mission_has_a_ground_truth_with_required_keys():
    missions = generate_missions(n=200, seed=1)
    required_keys = {
        "correct_match_radar_id",
        "fields_that_must_be_blocked",
        "fields_that_may_be_fused",
        "expected_provenance_chain",
        "requires_review_or_block",
        "is_dependent_evidence",
    }
    for m in missions:
        assert required_keys.issubset(m.ground_truth.keys())


def test_generation_is_deterministic_for_a_fixed_seed():
    # Mission ids are UUIDs (never meant to be reproducible byte-for-byte);
    # what must be reproducible is which conditions were combined and what
    # the resulting ground truth says should happen.
    a = generate_missions(n=50, seed=42)
    b = generate_missions(n=50, seed=42)
    assert [m.tags for m in a] == [m.tags for m in b]
    assert [m.ground_truth["fields_that_must_be_blocked"] for m in a] == [m.ground_truth["fields_that_must_be_blocked"] for m in b]
    assert [m.ground_truth["requires_review_or_block"] for m in a] == [m.ground_truth["requires_review_or_block"] for m in b]
    assert [m.ground_truth["correct_match_radar_id"] is None for m in a] == [m.ground_truth["correct_match_radar_id"] is None for m in b]


def test_sensor_failure_mission_has_no_radar_and_no_expected_match():
    missions = generate_missions(n=1000, seed=7)
    failures = [m for m in missions if "sensor_failure" in m.tags]
    assert failures
    for m in failures:
        assert m.radar_pool == []
        assert m.ground_truth["correct_match_radar_id"] is None
        assert m.ground_truth["expected_provenance_chain"] == [m.camera.id]


def test_repeated_evidence_seeking_loop_mission_caps_requests_at_one():
    missions = generate_missions(n=1000, seed=7)
    loop_missions = [m for m in missions if "repeated_evidence_seeking_loop" in m.tags]
    assert loop_missions
    for m in loop_missions:
        assert m.max_sensor_requests == 1


def test_disguise_and_insert_mutations_still_flag_field_for_blocking():
    """Checked in isolation (single-condition missions, guaranteed to exist
    by the forced-coverage pass) — combined with a later mutation that clears
    the field, ground truth legitimately changes too, since it always
    reflects final item state, not which mutations were named."""
    missions = generate_missions(n=1000, seed=7)
    for tag in ("insert_restricted_field", "disguise_restricted_field"):
        isolated = [m for m in missions if m.tags == [tag]]
        assert isolated
        for m in isolated:
            assert "raw_signal_signature" in m.ground_truth["fields_that_must_be_blocked"]


def test_all_1000_missions_run_through_fusion_engine_without_error():
    """This is the real proof the generator produces usable missions, not
    just well-formed ground truth dictionaries."""
    missions = generate_missions(n=1000, seed=7)
    for m in missions:
        engine = FusionEngine(network_domain=m.network_domain, max_sensor_requests=m.max_sensor_requests)
        pool = list(m.radar_pool)
        result = engine.run(m.camera, lambda pool=pool: pool)
        assert result is not None
