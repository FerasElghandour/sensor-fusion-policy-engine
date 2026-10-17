# Five-minute engineering walkthrough

## 1. Problem and system boundary

Open the README and architecture document. Explain why the policy layer is
separate from the reference fusion pipeline, and why a learned scorer cannot
choose the enforcement action. Identify which data is synthetic.

## 2. Consistent policy updates

Show `tests/test_policy_consistency.py`: a reload occurs between camera and
radar processing, but that mission keeps one version. Then show
`tests/test_service_state.py`: two OS processes compete for revision 1;
exactly one commits and the other reports a conflict.

## 3. Failure and recovery

Show invalid-update rollback, simulated audit-write failure, process termination
before commit, database corruption failing closed, and decision audit lookup
after application restart. Explain the single-host SQLite tradeoff.

## 4. Results and an actual discovered defect

Open VALIDATION.md and the saved results. Explain the matching-recall correction.
Show the seven stale camera-oracle labels in the discovery run and the combined-
mutation regression tests. The fix corrects labels; it does not change which
camera records the enforcement engine accepts.

Explain why deterministic association remains the default when it outperforms
the learned alternative. Do not describe this as a demonstrated model advantage.

## 5. Reproduction and remaining evidence

Run the standard-library result verifier if desired. Show the evidence ledger:
independent reproduction, real sensor/policy data, identity integration,
production monitoring and personal contribution history remain separate work.
The optional dashboard and real network performance are not freshly certified.
