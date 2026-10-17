# Threat Model

Scope: this is a synthetic-data proof-of-concept. No real sensors,
classified systems, weapons, or operational data are used or connected. This
document covers threats to the *fusion + compliance logic itself* — not
network security, authentication, or infrastructure hardening, which are out
of scope for this POC.

Each threat below maps to a concrete adversarial condition in
`adversarial_generator.py` (tag names in backticks) and to the tests that
exercise it.

## 1. Incorrect metadata

**Threat:** a sensor reports metadata that is wrong but well-formed (e.g. a
classification level that understates true sensitivity, or a mislabeled
field).

**Mitigation:** `MISCLASSIFIED_FIELD` (`policies/default_policy.yaml`)
doesn't trust the declared `classification_level` at all for sensitivity
purposes — it checks the *actual field content* against
`field_sensitivity_map` regardless of the label. Tags: `incorrect_classifications`,
`missing_classifications`. Tests: `tests/test_policy_engine.py::test_misclassified_field_requires_review`,
`tests/test_v02_acceptance.py::test_100_percent_of_forbidden_fields_blocked`.

**Residual risk:** only fields present in `field_sensitivity_map` are
checked. A field not listed there is trusted at face value.

## 2. Missing metadata

**Threat:** timestamps, locations, or classifications absent entirely.

**Mitigation:** `time_alignment_engine.is_missing_timestamp`/`within_window`
treat missing timestamps as non-alignable (never silently assumed aligned).
`ai_entity_association.extract_features` scores missing data as a *large
gap* (999.0), never imputed favorably. `active_sensor_request_planner`
detects missing fields and requests more evidence. Tags: `missing_timestamps`,
`sensor_failure`. Tests: `tests/test_time_alignment.py`,
`tests/test_ai_entity_association.py::test_missing_data_is_scored_as_a_gap_not_imputed_favorably`.

**Residual risk:** if *all* radar evidence is missing (`sensor_failure`), the
system correctly reports "no match" rather than guessing — but it also can't
recover information that was never sent.

## 3. Malicious metadata

**Threat:** an adversarial source deliberately smuggles a restricted field
into a payload it claims is fully authorized (`insert_restricted_field`), or
additionally obfuscates the value (`disguise_restricted_field`).

**Mitigation:** `MISCLASSIFIED_FIELD` and `RESTRICTED_CROSS_DOMAIN` block by
**field name**, independent of the declared classification or release
permissions the attacker attached. `disguise_restricted_field` proves
detection survives value obfuscation (base64) within the same tracked field.
Tests: `tests/test_v02_acceptance.py::test_100_percent_of_forbidden_fields_blocked`
(parametrized over both tags), `tests/test_adversarial_generator.py::test_disguise_and_insert_mutations_still_flag_field_for_blocking`.

**Residual risk — real and documented:** detection is by field *name*, not
by inspecting content. An attacker who relocates the sensitive payload into a
field *outside* `field_sensitivity_map` (e.g. stuffing it into a permitted
field the schema doesn't type-check for content) would not be caught by this
mechanism. Mitigating this fully would require content classification, which
this POC does not implement. Adding new sensitive fields to
`field_sensitivity_map` closes this gap incrementally, not exhaustively.

## 4. Unauthorized cross-domain fusion

**Threat:** a request to fuse data into a network domain the data isn't
released for.

**Mitigation:** every policy rule's `release_authority` condition checks the
requested *destination* domain against the item's own `release_permissions`
— `FORBIDDEN_DOMAIN` (REJECT), `RESTRICTED_CROSS_DOMAIN` (SEGREGATE), and
`SENSITIVE_MASKING` (RESTRICT) all key off this. Tag:
`unauthorized_cross_domain_request`. Tests:
`tests/test_policy_engine.py::test_confidential_unreleased_is_rejected`,
`tests/test_v02_acceptance.py::test_zero_unauthorized_fields_in_fusion_outputs`.

**Residual risk:** the domain model (`open`/`partner`/`internal`/
`restricted_net`) is a flat enum for this POC — no domain hierarchy or
transitive trust relationships are modeled.

## 5. Policy misconfiguration

**Threat:** a bad or contradictory policy update is deployed.

**Mitigation:** `PolicyFile` validation is fail-closed: a file with zero
rules, duplicate `rule_id`s, or **no unconditional catch-all rule** is
rejected before it ever becomes active (`PolicyLoadError`). `PolicyEngine`
validates fully before swapping (`reload_from_text`/`reload_from_path`) — a
bad candidate never touches `engine.policy`. Rules that overlap in
applicability (`policy_conflict` tag — e.g. an item matching both
`RESTRICTED_CROSS_DOMAIN` and `MISSING_RELEASE_PERMISSION`) are resolved
deterministically by `rule_priority`, always the same way. Tests:
`tests/test_policy_loader.py`, `tests/test_v02_acceptance.py::test_invalid_policy_reload_preserves_last_valid_policy`.

**Residual risk:** schema validation catches structural problems (missing
fields, no catch-all, duplicate IDs) but not *semantic* misconfiguration — a
syntactically valid policy that is simply too permissive (e.g. someone sets
`RESTRICTED_CROSS_DOMAIN`'s `enforcement_action` to `PERMIT`) will be loaded
and enforced exactly as written. Policy correctness review remains a human
responsibility; the engine only guarantees mechanical safety of the reload.

## 6. Model uncertainty

**Threat:** the AI association model is unsure which candidate is correct.

**Mitigation:** the model always returns a numeric `match_probability`
(never a bare boolean with hidden confidence) plus a per-feature
explanation, so downstream consumers can see *how* uncertain a call was.
The model is advisory only — even a wrong or uncertain match still passes
through the same policy engine before anything is permitted, so model
uncertainty affects *which* candidate gets fused, never *whether* compliance
is enforced. `reports/failure_analysis.md` (generated by every benchmark
run) lists concrete "AI model was uncertain" cases (`match_probability`
0.4-0.6).

**Residual risk:** the model can still confidently pick the *wrong*
candidate (a false positive) — see `reports/failure_analysis.md`'s "common
false matches" section for the conditions where this happens most
(`missing_timestamps` was the top contributor in the last run). This is why
acceptance target 8 only requires beating the *static-threshold* baseline,
not the deterministic one.

## 7. Evidence duplication

**Threat:** the same underlying observation appears twice, or a derived
value is fed back in as if it were independent confirmation, artificially
inflating fused confidence.

**Mitigation:** `evidence_dependency_graph.EvidenceDependencyGraph` tracks
`parent_data_ids` lineage; `uncertainty_engine.fuse_confidence()` only
compounds via noisy-OR when two pieces of evidence are provably independent
(no ancestor/descendant relationship, no shared ancestor) — otherwise it
caps at the stronger single observation. Tags: `duplicate_evidence`,
`evidence_derived_from_same_source`. Tests:
`tests/test_uncertainty.py::test_dependent_evidence_does_not_increase_confidence`,
`tests/test_v02_acceptance.py::test_dependent_evidence_never_inflates_confidence`.

**A documented architectural property, verified directly:** this system's
`FusionEngine` only ever fuses *one* candidate per camera detection per run.
A duplicated radar reading sitting alongside its original in the same pool
therefore never gets combined with the original in a single fusion — whether
the engine happens to select the original or its duplicate, the resulting
math is the same (fusing camera + one radar reading). The dependency graph
*additionally* correctly flags original↔duplicate as dependent (verified in
`tests/test_dependency_graph.py` and interactively during development), so
if a future version fuses multiple radar candidates simultaneously, the
existing lineage tracking already prevents inflated double-counting.

## 8. Provenance tampering

**Threat:** a conclusion is presented without a trustworthy trail back to
its raw inputs, or that trail is incomplete/falsified.

**Mitigation:** `provenance_recorder.ProvenanceRecorder` builds a NetworkX
DAG and mirrors every item and conclusion to SQLite as it's processed —
provenance is recorded *during* the run, not reconstructed after the fact
from data that could have been altered. `trace_to_inputs()` is a pure graph
traversal, not a claim the system makes about itself. Tests:
`tests/test_provenance.py`, `tests/test_v02_acceptance.py::test_100_percent_fusion_outputs_traceable`.

**Residual risk:** provenance is in-process/SQLite for this POC (per
`FusionEngine` instance, `:memory:` by default) — there is no cryptographic
signing or tamper-evidence on the stored records themselves. A system with
write access to the SQLite file could alter history after the fact. Not
addressed in this POC; would need signed/append-only storage in a production
system.

## 9. Policy reload failure

**Threat:** a reload operation itself fails partway, or a malformed request
degrades or crashes the running policy engine.

**Mitigation:** the reload path is validate-then-swap, never
patch-in-place — `load_policy_text()` builds and fully validates a new
`PolicyFile` object before `PolicyEngine.policy` is ever reassigned. If
validation raises at any point (bad YAML, schema violation, missing
catch-all), the assignment simply never happens. Tag: `rapid_policy_change`
(benchmarked by reloading the shared policy engine, mission by mission, and
confirming the next mission still resolves correctly — see
`benchmarks/approaches.py::_run_batch_with_policy_churn`). Tests:
`tests/test_benchmark_approaches.py::test_rapid_policy_change_missions_reflect_the_alternate_policy_version`.

**Residual risk:** reload is synchronous and single-threaded in this POC. A
concurrent-request race during reload (a request evaluated mid-swap) isn't
exercised here — `benchmarks` model rapid *sequential* changes, not
concurrent ones.

## 10. Denial-of-service through repeated requests

**Threat:** a fusion loop keeps requesting more sensor evidence indefinitely
(resource exhaustion, or a wedged operator waiting forever).

**Mitigation:** `active_sensor_request_planner.SensorRequestPlanner` enforces
a hard `max_requests` cap — once reached, further calls to `.request()`
return `None` and log a `LIMIT_REACHED` entry instead of issuing another
request. This is a structural cap (a counter compared against a fixed
limit), not a timeout or heuristic. Tag: `repeated_evidence_seeking_loop`
(mission-level `max_sensor_requests=1`). Tests:
`tests/test_sensor_request_planner.py::test_request_loop_stops_at_configured_limit`,
`tests/test_v02_acceptance.py::test_evidence_seeking_loops_always_terminate`
(verified across all 500+ benchmarked missions, all three approaches, 100%
termination rate).

**Residual risk:** the cap bounds *this system's own* request loop; it does
not defend against an external actor flooding the system with many separate
fusion requests (a different, infrastructure-level DoS concern out of scope
for this POC).
