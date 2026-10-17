# Fusion Compliance Loop — Adversarial Benchmark Report

Generated: 2026-07-15T19:25:11.751711+00:00
Missions: 1000 (seed=7, 23 adversarial conditions combined)

All numbers below come from an actual run of `python -m benchmarks.run_all` against synthetic data only. See docs/BENCHMARK_METHOD.md for definitions.

## Approach comparison

### Entity-association performance (secondary — the reference fusion pipeline, not the FCE)

| Metric | A: static threshold, no compliance | B: deterministic + compliance | C: model-based + compliance |
|---|---|---|---|
| Precision | 0.9828 | 0.9769 | 0.9595 |
| Recall | 0.7459 | 0.9285 | 0.9273 |
| F1 score | 0.8481 | 0.9521 | 0.9431 |
| False fusion rate | 0.012 | 0.02 | 0.035 |
| Missed fusion rate | 0.2541 | 0.0715 | 0.0727 |

### Compliance enforcement performance (primary — the Fusion Compliance Engine)

| Metric | A: static threshold, no compliance | B: deterministic + compliance | C: model-based + compliance |
|---|---|---|---|
| Policy violation detection rate | 0.2592 | 1.0 | 1.0 |
| Unauthorized field leakage rate | 0.646 | 0.0 | 0.0 |
| Unauthorized field leakage count | 646 | 0 | 0 |
| Unauthorized record leakage rate | 1.0 | 0.0 | 0.0 |
| Unauthorized record leakage count | 65 | 0 | 0 |
| Missing-metadata detection rate | 0.0 | 0.863 | 0.8493 |
| Misclassification detection rate | 0.2121 | 1.0 | 1.0 |
| Cross-domain violation detection rate | 0.2054 | 1.0 | 1.0 |
| Protected B isolation rate | 0.2462 | 1.0 | 1.0 |
| False compliance-alert rate | 0.0 | 0.0 | 0.0 |
| Audit completeness | 0.0 | 1.0 | 1.0 |
| Provenance completeness | 0.0 | 1.0 | 1.0 |
| Explanation coverage | 0.0 | 1.0 | 1.0 |
| Evidence-loop termination rate | 1.0 | 1.0 | 1.0 |
| Downstream contamination rate | 0.0 | 0.0 | 0.0 |

### Latency (compliance-enforcement path)

| Metric | A: static threshold, no compliance | B: deterministic + compliance | C: model-based + compliance |
|---|---|---|---|
| Avg latency (s) | 2e-06 | 0.001163 | 0.00154 |
| P95 latency (s) | 3e-06 | 0.001481 | 0.002041 |


## Key findings

- Approach A leaked restricted fields on 646 of 1000 missions; B and C leaked on 0 and 0.
- C (model-based) F1=0.9431 vs A (static threshold) F1=0.8481 — beats the naive baseline (acceptance target 8).
- B (deterministic) F1=0.9521; C does not beat B's F1 on this run — see failure_analysis.md.
- Provenance completeness: A=0.0, B=1.0, C=1.0.
- Explanation coverage: A=0.0, B=1.0, C=1.0.
- Evidence-loop termination rate: A=1.0, B=1.0, C=1.0.

See failure_analysis.md for per-condition breakdowns and remaining risks.
