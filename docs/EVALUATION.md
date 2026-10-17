# Evaluation

Use [VALIDATION.md](VALIDATION.md) for the fresh test results, benchmark table and transport-specific performance measurements.

Matching precision/recall/F1 use metric version 2.0. An incorrect non-null match contributes both a false predicted link and a missed true link. Policy enforcement outcomes are reported separately. The ground-truth generator now recomputes camera rejection from the final classification, permissions and destination, including when other mutations remove the radar pool.

The three mission seeds vary synthetic cases, not model-training seeds. This is a useful stress test of the prototype, not evidence of operational generalization. There is no independently collected sensor dataset or external policy-authority review.

The standard-library `scripts/check_evidence.py` checks source/case hashes and independently recomputes matching and selected enforcement counts from saved outcomes. It does not import the production metric implementation. For archived discovery evidence whose code has since changed, `--recorded-only` checks saved predictions but explicitly skips comparison with current source files.

No project outcome in this package establishes personal independent authorship, production adoption, real business impact or certification. Those require separate evidence.
