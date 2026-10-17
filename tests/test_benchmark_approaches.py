from fusion_compliance_loop.adversarial_generator import generate_missions
from benchmarks.approaches import run_approach_a_batch, run_approach_b_batch, run_approach_c_batch
from benchmarks.metrics import compute_metrics

# Kept small so the regular test suite stays fast; benchmarks/run_all.py runs
# the full 1000+ mission set for the actual reported numbers.
MISSIONS = generate_missions(n=150, seed=7)


def test_approach_a_has_no_provenance_or_explanation():
    outcomes = run_approach_a_batch(MISSIONS)
    assert all(o.provenance_chain == [] for o in outcomes)
    assert all(o.explanation == "" for o in outcomes)


def test_approach_b_and_c_have_full_provenance_and_explanation_coverage():
    for outcomes in (run_approach_b_batch(MISSIONS), run_approach_c_batch(MISSIONS)):
        metrics = compute_metrics(MISSIONS, outcomes)
        assert metrics["provenance_completeness"] == 1.0
        assert metrics["explanation_coverage"] == 1.0
        assert metrics["evidence_loop_termination_rate"] == 1.0


def test_approach_a_leaks_restricted_fields_that_b_and_c_block():
    metrics_a = compute_metrics(MISSIONS, run_approach_a_batch(MISSIONS))
    metrics_b = compute_metrics(MISSIONS, run_approach_b_batch(MISSIONS))
    metrics_c = compute_metrics(MISSIONS, run_approach_c_batch(MISSIONS))
    assert metrics_a["unauthorized_leakage_count"] > 0
    assert metrics_b["unauthorized_leakage_count"] == 0
    assert metrics_c["unauthorized_leakage_count"] == 0


def test_no_errors_across_any_approach():
    for outcomes in (run_approach_a_batch(MISSIONS), run_approach_b_batch(MISSIONS), run_approach_c_batch(MISSIONS)):
        assert all(o.error is None for o in outcomes)


def test_every_b_and_c_decision_carries_policy_id_and_version_when_a_match_was_fused():
    for outcomes in (run_approach_b_batch(MISSIONS), run_approach_c_batch(MISSIONS)):
        for o in outcomes:
            if o.fused_fields_present or o.blocked_fields:
                assert o.policy_id
                assert o.policy_version


def test_rapid_policy_change_missions_reflect_the_alternate_policy_version():
    outcomes = run_approach_b_batch(MISSIONS)
    by_id = {m.mission_id: m for m in MISSIONS}
    reloaded = [
        o for o in outcomes
        if "rapid_policy_change" in by_id[o.mission_id].tags and o.policy_version is not None
    ]
    assert reloaded
    assert any(o.policy_version == "1.1.0" for o in reloaded)
    # policy state must not leak into the NEXT (non-tagged) mission
    non_tagged_after = [
        o for o in outcomes
        if "rapid_policy_change" not in by_id[o.mission_id].tags and o.policy_version is not None
    ]
    assert any(o.policy_version == "1.0.0" for o in non_tagged_after)


def test_metrics_keys_and_ranges_are_sane():
    outcomes = run_approach_b_batch(MISSIONS)
    metrics = compute_metrics(MISSIONS, outcomes)
    for key in ("precision", "recall", "f1_score", "false_fusion_rate", "missed_fusion_rate",
                "policy_violation_detection_rate", "unauthorized_leakage_rate",
                "provenance_completeness", "explanation_coverage", "evidence_loop_termination_rate"):
        assert 0.0 <= metrics[key] <= 1.0, f"{key}={metrics[key]} out of [0,1]"
    assert metrics["avg_latency_s"] >= 0
    assert metrics["p95_latency_s"] >= metrics["avg_latency_s"] * 0.5  # p95 shouldn't be wildly below the mean
