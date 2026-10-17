# Failure Analysis

Generated: 2026-07-15T19:25:11.751711+00:00

## A_static_threshold_no_compliance

### Common false matches (by adversarial condition)
- communication_delay: 10
- duplicate_evidence: 3
- unauthorized_cross_domain_request: 2
- missing_timestamps: 2
- multiple_possible_matches: 2
- disguise_restricted_field: 1
- missing_metadata_markings: 1
- sensor_noise: 1
- protected_b_cross_domain: 1
- rapid_policy_change: 1

### Common missed matches (by adversarial condition)
- missing_timestamps: 67
- clock_drift: 53
- conflicting_locations: 51
- delayed_timestamps: 49
- communication_delay: 44
- duplicate_evidence: 19
- corrupted_metadata: 18
- missing_release_permission: 17
- sensor_noise: 15
- unauthorized_cross_domain_request: 15

### Latency bottleneck conditions (highest avg latency)
- communication_delay: 0.003 ms avg
- clock_drift: 0.003 ms avg
- conflicting_locations: 0.003 ms avg
- delayed_timestamps: 0.003 ms avg
- duplicate_evidence: 0.002 ms avg

### Execution errors
- no execution errors observed

## B_deterministic_plus_compliance

### Common false matches (by adversarial condition)
- communication_delay: 12
- multiple_possible_matches: 9
- duplicate_evidence: 6
- delayed_timestamps: 5
- missing_timestamps: 3
- unauthorized_cross_domain_request: 2
- protected_b_cross_domain: 2
- sensor_noise: 2
- repeated_evidence_seeking_loop: 1
- disguise_restricted_field: 1

### Common missed matches (by adversarial condition)
- camera_side_forbidden_domain: 65
- multiple_possible_matches: 7
- missing_release_permission: 7
- missing_classifications: 6
- incorrect_classifications: 6
- missing_metadata_markings: 5
- evidence_derived_from_same_source: 4
- repeated_evidence_seeking_loop: 4
- conflicting_locations: 4
- sensor_noise: 4

### Latency bottleneck conditions (highest avg latency)
- duplicate_evidence: 1.399 ms avg
- protected_b_cross_domain: 1.375 ms avg
- rapid_policy_change: 1.312 ms avg
- unauthorized_cross_domain_request: 1.268 ms avg
- communication_delay: 1.233 ms avg

### Execution errors
- no execution errors observed

## C_ai_assisted_plus_compliance

### Common false matches (by adversarial condition)
- missing_timestamps: 29
- duplicate_evidence: 7
- multiple_possible_matches: 6
- communication_delay: 6
- disguise_restricted_field: 4
- clock_drift: 4
- missing_release_permission: 4
- corrupted_metadata: 4
- policy_conflict: 2
- protected_b_cross_domain: 2

### Common missed matches (by adversarial condition)
- camera_side_forbidden_domain: 65
- multiple_possible_matches: 7
- missing_release_permission: 7
- missing_classifications: 6
- incorrect_classifications: 6
- missing_metadata_markings: 5
- evidence_derived_from_same_source: 4
- repeated_evidence_seeking_loop: 4
- conflicting_locations: 4
- sensor_noise: 4

### Latency bottleneck conditions (highest avg latency)
- duplicate_evidence: 1.940 ms avg
- unauthorized_cross_domain_request: 1.692 ms avg
- rapid_policy_change: 1.685 ms avg
- untagged: 1.677 ms avg
- protected_b_cross_domain: 1.665 ms avg

### Execution errors
- no execution errors observed

### Scenarios where the AI model was uncertain (match probability 0.4-0.6)
- mission-00577 (tags=['delayed_timestamps', 'multiple_possible_matches']): probability=0.4951
- mission-00914 (tags=['delayed_timestamps', 'unauthorized_cross_domain_request']): probability=0.5102
- mission-00771 (tags=['delayed_timestamps']): probability=0.5143
- mission-00515 (tags=['clock_drift', 'delayed_timestamps', 'missing_release_permission']): probability=0.5206
- mission-00490 (tags=['clock_drift']): probability=0.4775
- mission-00425 (tags=['clock_drift', 'corrupted_metadata']): probability=0.5278
- mission-00821 (tags=['delayed_timestamps']): probability=0.5284
- mission-00372 (tags=['clock_drift']): probability=0.5381
- mission-00505 (tags=['corrupted_metadata', 'delayed_timestamps', 'duplicate_evidence']): probability=0.4473
- mission-00037 (tags=['delayed_timestamps']): probability=0.562
- mission-00189 (tags=['delayed_timestamps', 'sensor_noise']): probability=0.4299
- mission-00292 (tags=['clock_drift', 'duplicate_evidence']): probability=0.4257
- mission-00102 (tags=['delayed_timestamps', 'sensor_noise']): probability=0.4095

## Remaining technical risks

- **Content-based disguise is only caught by field name, not field content.** The policy engine's `field_sensitivity_map` blocks by field *name*; `disguise_restricted_field` proves detection survives value obfuscation (base64) within the *same* tracked field, but relocating the payload into a field outside the map would not be caught by this mechanism. See docs/THREAT_MODEL.md.
- **The model-based approach (C) does not strictly beat the deterministic baseline (B)** on every run — its synthetic training distribution differs from the mission generator's exact structure. It reliably clears the required bar (beating the static-threshold baseline A) but is not a guaranteed upgrade over B.
- **Approach A has zero policy enforcement by design** — its leakage/violation numbers describe a system with no compliance controls at all, included only as a naive floor for comparison, never for real use.
- **Missions are synthetic** and do not model real correlated sensor failures, timing attacks against the exact moment of a policy reload, or multi-object clutter scenes.
- **Missing-metadata detection rate is not 1.0 for B/C.** The AI compliance-risk detector's escalation threshold (0.85) is not always crossed by the `missing_metadata_markings` condition alone — three of ten risk features move, but the other seven vary with the rest of the item's (otherwise normal) state. This is a real, measured gap, not rounded away — see docs/MODEL_CARD.md.
- **Entity-association metrics (F1, recall) and compliance metrics must be read separately.** `camera_side_forbidden_domain` missions correctly block the camera before any radar match is attempted — correct compliance behavior — but this counts as a *missed* match under precision/recall, which is why this report groups entity-association and compliance metrics into separate tables rather than one score.
