# Benchmark Method

How `python -m benchmarks.run_all` produces the numbers in
`reports/benchmark_report.md` and `reports/failure_analysis.md`.

## Mission generation

`adversarial_generator.generate_missions(n=1000, seed=7)` builds `n`
independent fusion missions. Each mission starts from a clean synthetic
camera detection + 3-candidate radar pool
(`synthetic_sensor_generator.make_camera_detection`/`make_radar_pool`), then
applies 0-3 of 23 adversarial conditions (see `ADVERSARIAL_CONDITIONS`) — 20
from v0.2, plus three added in the v0.3 official-challenge-text audit:
`missing_metadata_markings` (drives the AI compliance-risk detector's
escalation path), `camera_side_forbidden_domain` (proves the camera
modality is genuinely gated, not just radar), and `protected_b_cross_domain`
(exercises the synthetic Protected B classification level and the
`canada_protected`/`coalition_unclassified` network domains).

- The first `2 × 23 = 46` missions each apply exactly **one** condition in
  isolation (guaranteed single-factor coverage).
- The remainder combine a random subset (weighted toward 1-2 conditions,
  occasionally 0 for a clean control mission or 3 for a harder combination).
- Every mission carries **ground truth**, computed once after all mutations
  finish (`_finalize_ground_truth`) so combined conditions can't leave a
  stale answer from an earlier mutation: the correct match (or `None` if no
  match should exist, e.g. `sensor_failure`), which fields must be blocked,
  which may be fused, the expected provenance chain, whether the situation
  requires review/blocking, and whether the true match is lineage-dependent.
- Generation is deterministic for a fixed seed (mission composition and
  ground truth reproduce exactly; mission IDs are UUIDs and are not expected
  to match byte-for-byte between runs).

Default run: **1,000 missions, seed 7**. Verified to run through the full
fusion pipeline with **0 errors** (`tests/test_adversarial_generator.py::test_all_1000_missions_run_through_fusion_engine_without_error`).

## The three approaches

| | A | B | C |
|---|---|---|---|
| Association | Static time+distance threshold (first candidate within 2s / 20m, no ranking) | `entity_association_engine.rank_candidates` (weighted: time, location, direction, confidence) | `ai_entity_association.ai_rank_candidates` (logistic regression, see docs/MODEL_CARD.md) |
| Compliance | **None** — every matched field is fused unfiltered | `policy_engine.apply()` (YAML-driven rules) | Same `policy_engine.apply()` |
| Provenance | None | `provenance_recorder` | `provenance_recorder` |
| Explanation | None | `FusionResult.explanation` | `FusionResult.explanation` |

A exists only as a naive floor — it shows what leaks when nothing enforces
policy. B and C always route the winning candidate through the *identical*
policy application and confidence-fusion code (see ARCHITECTURE.md, "AI
never bypasses policy").

Missions tagged `rapid_policy_change` reload a shared `PolicyEngine` to
`policies/alt_policy_v1_1.yaml` for that one mission, then reload back to
the default immediately after — this exercises a live reload cycle
repeatedly across the batch, not once at startup
(`benchmarks/approaches.py::_run_batch_with_policy_churn`).

## Matching metrics: version 2.0

A correct non-null association contributes one TP. A wrong non-null association
contributes one FP **and**, when a true match exists, one FN for the missed true
link. Abstaining when a true match exists contributes one FN. Correctly predicting
no match contributes one TN. Because an incorrect association can create two
link errors, TP + FP + FN + TN need not equal the number of missions.

- Precision = correctly predicted links / all predicted links.
- Recall = correctly predicted links / all ground-truth links.
- F1 = harmonic mean of those two rates.
- `wrong_match_count` counts incorrect non-null predictions when a true match exists.
- `ground_truth_match_count` is identical across approaches on the same cases.
- Wrong ordering, duplicate mission IDs and invalid latency samples are rejected.

Older files under `reports/` remain historical metric-version-1 evidence. That
recall excluded wrong non-null matches from its denominator. Their F1 values must
not be presented as current results or compared directly with version 2.0.
See [VALIDATION.md](VALIDATION.md) for fresh results and raw saved predictions.

Entity association and policy enforcement are separate outcomes: rejecting a
camera correctly can prevent an association, so matching recall alone is not a
policy-safety metric. Warm mission latency includes the local compliance and
provenance path, but excludes HTTP, TLS, networking and production contention.

**Primary compliance metrics (v0.3)** — these measure the Fusion Compliance
Engine itself, separately from the entity-association metrics above (which
measure the *reference fusion pipeline*, not the FCE):

| Metric | Formula |
|---|---|
| Unauthorized record leakage rate / count | Of missions where the ground truth expects the *camera* to be rejected outright, the fraction/count where it wasn't |
| Missing-metadata detection rate | Of `missing_metadata_markings`-tagged missions, the fraction where the final disposition was not a bare PERMIT or the AI flagged ≥1 risk category |
| Misclassification detection rate | Of missions tagged `missing_classifications`/`incorrect_classifications`, the fraction where must-block fields did not leak |
| Cross-domain violation detection rate | Of missions tagged `unauthorized_cross_domain_request`/`camera_side_forbidden_domain`/`protected_b_cross_domain`, the fraction correctly blocked (record- and field-level) |
| Protected B isolation rate | Of `protected_b_cross_domain`-tagged missions, the fraction where the sensitive field did not leak |
| False compliance-alert rate | Of missions with **no** adversarial tags at all, the fraction where the AI compliance-risk detector still flagged ≥1 risk category |
| Audit completeness | Of missions with any policy action recorded, the fraction that also carry a policy ID, policy version, and explanation |
| Downstream contamination rate | Fraction of missions where a field the policy blocked still appears in `fused_fields_present` — expected to be 0 whenever the FCE is enforcing anything (note: vacuously 0 for approach A too, since A never declares any blocked fields — see `unauthorized_leakage_rate` for A's real leakage) |

All definitions live in `benchmarks/metrics.py::compute_metrics` — this
document describes that code, it does not duplicate independent logic.

**A measured, disclosed interaction worth knowing about:** `camera_side_forbidden_domain`
missions correctly block the camera *before* any radar match is attempted —
correct FCE behavior — but this counts as a missed match (FN) under
precision/recall, which pulls entity-association F1 down for B/C relative
to a mission set without that condition. This is exactly why this
document, `reports/benchmark_report.md`, and the dashboard present
entity-association and compliance metrics as two separate tables rather
than one blended score.

## Failure analysis

`benchmarks/failure_analysis.py::analyze_failures` tallies, per approach:
false matches and missed matches grouped by adversarial condition tag,
average latency per tag (bottleneck ranking), any execution errors, and (for
approach C only) missions where `top_candidate_score` fell in `[0.4, 0.6]`
("the AI model was uncertain").

## Reproducing the current protocol

```sh
python scripts/evaluate_system.py --output validation/new-run --mission-count 1000 --seeds 7 19 42
python scripts/check_evidence.py validation/new-run/results.json
```

This writes a new directory containing every case/outcome, source hashes,
environment versions and an in-process two-application API probe. Existing
historical reports are not overwritten. See [VALIDATION.md](VALIDATION.md).

The legacy `python -m benchmarks.run_all` entry point still exists and writes
`reports/`; it is not the preservation-oriented reproduction command above.
The HTTP benchmark endpoint is admin-only, capped at 500 missions and never
writes reports or changes the active service policy.
