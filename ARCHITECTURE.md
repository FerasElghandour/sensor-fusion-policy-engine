# Architecture

## Data path

1. The service reads the latest committed policy revision from SQLite.
2. That revision creates a detached `PolicyEngine` for one `FusionEngine` mission.
3. The compliance layer inspects the camera and each radar candidate independently. A local learned risk model may make a policy condition eligible; it cannot change rule priority or choose an enforcement action.
4. The policy engine filters restricted fields. Only the filtered record is inserted into provenance storage. Rejected records retain only an ID/rejected tombstone.
5. A reference downstream pipeline combines approved dispositions. It is not a real sensor-fusion integration.
6. The API persists the decision explanation, policy revision/hash, filtered provenance nodes and audit events. Other local workers and a restarted application can retrieve them within the retention window.

Ranking still uses the reference candidate pool; the downstream numeric fusion step uses approved dispositions. `REQUIRE_REVIEW` is a recorded policy disposition with field filtering; there is no implemented human approval queue or identity-backed release process. `permitted_fields` remains descriptive, as documented in the policy format. This prototype must not be treated as an operational authorization service.

## Control path

An admin submits validated policy text plus `expected_revision`. One SQLite transaction checks that revision, appends the new policy and appends its audit record. A stale writer gets HTTP 409; it must reread current state. Invalid text never replaces the active policy. Repeating identical content is idempotent. Restoring old content creates a new revision and audit entry.

In-flight missions continue with their original snapshot. New missions read the latest committed state. Worker-local policy caches are not used, so sharing the same database path gives local workers one source of truth.

## Design decisions

### SQLite rather than a distributed datastore

The supported deployment is one host, several API workers, and one local filesystem database. WAL mode, short transactions, a five-second busy timeout and FULL synchronization provide a small, inspectable persistence boundary. Separate connections are opened and closed per operation; no SQLite connection crosses worker threads.

This avoids introducing a network service or consensus protocol into a local demonstration. It does not support multi-host coordination, a network filesystem, automatic failover or high availability. Those requirements would justify a service such as PostgreSQL plus an explicit migration/deployment design.

### Revision checks rather than last-writer-wins

A monotonically increasing database revision identifies a committed configuration, independently of the policy author's version string. Compare-and-swap rejects lost updates. Changing content while reusing the current policy version is rejected. Policy and audit writes succeed or roll back together.

### Snapshots rather than holding a lock throughout a mission

A copy of validated policy state lets a mission complete consistently without preventing an admin update. In-memory policy access is protected against concurrent mutation. Public policy objects are detached copies; direct mutation cannot change active rules.

### Bounded work rather than an unbounded request queue

Each application instance admits at most two scenario/benchmark jobs simultaneously. Excess work receives HTTP 429 with Retry-After. Benchmark requests are capped at 500 missions and arbitrary input bodies at 64 KiB, including chunked bodies. HTTP requests cannot write benchmark reports or mutate benchmark module globals.

These are local admission controls, not a distributed quota, hard CPU deadline or cancellation service. A future public deployment needs ingress timeouts, authentication infrastructure, disk monitoring and an explicit resource budget.

### Deterministic enforcement with advisory ML

A more complicated model is not assumed to be better. The fresh evaluation compares all three paths on identical generated missions. Matching quality, record/field enforcement and latency are reported separately. The deterministic association path remains the default.

## Evaluation boundaries

The offline benchmark deliberately uses isolated reference policies, including alternate-policy missions. It does not read or change the live API policy. In contrast, API scenarios and adversarial single-mission requests use the persisted active policy.

Multi-seed synthetic evaluation varies generated missions; it does not establish robustness to real sensors, different institutions' policies or independent data collection. The local model training seeds are fixed, so these are not multiple independent model-training trials.
