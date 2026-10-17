"""Explicit tests for the nine v0.2 acceptance targets. Run at n=500 (a
seed-stable sample, verified consistent across multiple seeds during
development — see docs/BENCHMARK_METHOD.md) so results are statistically
meaningful without slowing the regular test suite down too much.

These tests must never be weakened to pass — if one fails, the fix belongs
in the implementation, not here.
"""

import pytest
import yaml

from fusion_compliance_loop.adversarial_generator import generate_missions
from fusion_compliance_loop.policy_engine import PolicyEngine, PolicyLoadError, DEFAULT_POLICY_PATH
from benchmarks.approaches import run_approach_a_batch, run_approach_b_batch, run_approach_c_batch
from benchmarks.metrics import compute_metrics

MISSIONS = generate_missions(n=500, seed=7)
OUTCOMES_A = run_approach_a_batch(MISSIONS)
OUTCOMES_B = run_approach_b_batch(MISSIONS)
OUTCOMES_C = run_approach_c_batch(MISSIONS)
METRICS_A = compute_metrics(MISSIONS, OUTCOMES_A)
METRICS_B = compute_metrics(MISSIONS, OUTCOMES_B)
METRICS_C = compute_metrics(MISSIONS, OUTCOMES_C)


# 1. 100% of forbidden fields blocked.
@pytest.mark.parametrize("outcomes", [OUTCOMES_B, OUTCOMES_C], ids=["deterministic", "ai_assisted"])
def test_100_percent_of_forbidden_fields_blocked(outcomes):
    for mission, outcome in zip(MISSIONS, outcomes):
        must_block = mission.ground_truth["fields_that_must_be_blocked"]
        for forbidden_field in must_block:
            assert forbidden_field not in outcome.fused_fields_present, (
                f"{mission.mission_id} ({mission.tags}) leaked {forbidden_field}"
            )


# 2. 0 unauthorized fields in fusion outputs.
def test_zero_unauthorized_fields_in_fusion_outputs():
    assert METRICS_B["unauthorized_leakage_count"] == 0
    assert METRICS_C["unauthorized_leakage_count"] == 0


# 3. 100% of fusion outputs traceable to original inputs.
def test_100_percent_fusion_outputs_traceable():
    assert METRICS_B["provenance_completeness"] == 1.0
    assert METRICS_C["provenance_completeness"] == 1.0
    assert METRICS_B["fused_mission_count"] > 0
    assert METRICS_C["fused_mission_count"] > 0


# 4. 100% of policy decisions linked to a policy ID and version.
@pytest.mark.parametrize("outcomes", [OUTCOMES_B, OUTCOMES_C], ids=["deterministic", "ai_assisted"])
def test_100_percent_of_policy_decisions_linked_to_id_and_version(outcomes):
    decided = [o for o in outcomes if o.policy_action is not None]
    assert decided
    for outcome in decided:
        assert outcome.policy_id, f"{outcome.mission_id} missing policy_id"
        assert outcome.policy_version, f"{outcome.mission_id} missing policy_version"


# 5. Duplicate or dependent evidence must not incorrectly increase confidence.
#
# Scoped to missions where the item the engine ACTUALLY fused is lineage-
# dependent on the CAMERA specifically (camera.id in its parent_data_ids —
# the evidence_derived_from_same_source condition). A "duplicate_evidence"
# mission's duplicate is parented to the *original radar item*, not the
# camera: since this architecture only ever fuses one radar candidate per
# mission, fusing camera+duplicate is mathematically identical to fusing
# camera+original (same near-equal confidence) — there's no double-counting
# to guard against there, so it isn't part of this assertion's scope.
@pytest.mark.parametrize("outcomes", [OUTCOMES_B, OUTCOMES_C], ids=["deterministic", "ai_assisted"])
def test_dependent_evidence_never_inflates_confidence(outcomes):
    by_id = {m.mission_id: m for m in MISSIONS}
    checked = 0
    for outcome in outcomes:
        if outcome.confidence_after is None or outcome.predicted_match_radar_id is None:
            continue
        mission = by_id[outcome.mission_id]
        matched = next((r for r in mission.radar_pool if r.id == outcome.predicted_match_radar_id), None)
        if matched is None or mission.camera.id not in matched.parent_data_ids:
            continue
        checked += 1
        # fuse_confidence() rounds its result to 3 decimals, so allow for
        # that rounding granularity rather than comparing raw floats.
        ceiling = max(mission.camera.confidence_score, matched.confidence_score) + 5e-4
        assert outcome.confidence_after <= ceiling, (
            f"{mission.mission_id}: confidence {outcome.confidence_after} exceeded "
            f"the non-compounded ceiling {ceiling} for dependent evidence"
        )
    assert checked > 0, "no mission actually exercised the dependent-evidence path — test would be vacuous"


# 6. Evidence-seeking loops must always terminate.
def test_evidence_seeking_loops_always_terminate():
    assert METRICS_A["evidence_loop_termination_rate"] == 1.0
    assert METRICS_B["evidence_loop_termination_rate"] == 1.0
    assert METRICS_C["evidence_loop_termination_rate"] == 1.0


# 7. Invalid policy reloads must preserve the last valid policy.
def test_invalid_policy_reload_preserves_last_valid_policy():
    engine = PolicyEngine()
    good_version = engine.policy_version

    with pytest.raises(PolicyLoadError):
        engine.reload_from_text("{ this is not valid yaml: [")

    with pytest.raises(PolicyLoadError):
        broken = yaml.safe_load(DEFAULT_POLICY_PATH.read_text())
        del broken["rules"][0]["enforcement_action"]  # required field missing
        engine.reload_from_text(yaml.safe_dump(broken))

    assert engine.policy_version == good_version
    from fusion_compliance_loop.models import RadarDetection
    from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain

    item = RadarDetection(confidence_score=0.6, classification_level=ClassificationLevel.PUBLIC, release_permissions=[NetworkDomain.OPEN])
    assert engine.evaluate(item, NetworkDomain.OPEN).rule_name == "DEFAULT_PERMIT"


# 8. AI matching must outperform the static threshold baseline on F1 score.
def test_ai_matching_outperforms_static_threshold_baseline_on_f1():
    assert METRICS_C["f1_score"] > METRICS_A["f1_score"], (
        f"AI F1 {METRICS_C['f1_score']} did not beat static-threshold baseline F1 {METRICS_A['f1_score']}"
    )


# 9. Every automated decision must have a plain-English explanation.
def test_every_automated_decision_has_a_plain_english_explanation():
    assert METRICS_B["explanation_coverage"] == 1.0
    assert METRICS_C["explanation_coverage"] == 1.0
    for outcomes in (OUTCOMES_B, OUTCOMES_C):
        for outcome in outcomes:
            assert outcome.explanation
            assert outcome.explanation[0].isupper()
            assert outcome.explanation.strip().endswith(".")
