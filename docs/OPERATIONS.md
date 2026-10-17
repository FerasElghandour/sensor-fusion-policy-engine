# Local operation and recovery

## Supported boundary

Run on one host with a local SQLite database, shared by all API workers through the same absolute `FUSION_STATE_DB` path. Do not use a network filesystem. Protect the parent directory and keep the database outside any static/public website directory. New state files are created with owner-only permissions; storage encryption and host access control remain deployment responsibilities.

Both service credentials must be distinct, random and at least 32 characters. The implementation uses constant-time comparisons and does not log bearer tokens or request bodies. These shared role credentials do not identify individual humans. The policy audit records a service role, not verified personal identity.

## Endpoints

| Route | Role | Behavior |
|---|---|---|
| `GET /health` | Public | Process liveness; does not claim storage readiness. |
| `GET /ready` | Reader/admin | Checks persisted policy validity and checksum. |
| `GET /policy/version` | Reader/admin | Returns active revision, hash, policy ID/version. |
| `POST /policy/validate` | Admin | Validates text without activating it. |
| `POST /policy/reload` | Admin | Requires `text` and `expected_revision`; atomically changes policy and audit. |
| `GET /policy/history` | Admin | Returns up to 1,000 revision/audit entries. |
| `GET /scenarios/{name}` | Reader/admin | Executes a bounded synthetic demonstration and retains the resulting decision. |
| `GET /adversarial/run-one` | Reader/admin | Executes one generated case; index is limited to 0..499. |
| `GET /decisions/{id}/provenance` | Reader/admin | Returns retained, filtered provenance and policy context. |
| `GET /decisions/{id}/audit-log` | Reader/admin | Returns the actual retained decision's audit, including after restart. |
| `POST /benchmark/run` | Admin | Runs up to 500 isolated reference missions; HTTP report writes are disabled. |
| `GET /benchmark/results` | Reader/admin | Reads the retained historical report, explicitly labeled as historical. |

The older `/scenarios/{name}/audit-log` endpoint executes a new scenario. Use the decision-ID endpoint to retrieve the audit belonging to a particular retained result.

## Expected failure behavior

- 401: missing/invalid credentials; no state initialization is performed for that request.
- 403: authenticated reader attempted an admin operation.
- 409: stale policy revision, or changed content reused the active policy version.
- 413: actual received body exceeds the configured limit, regardless of Content-Length.
- 422: invalid request/schema, invalid policy or attempted HTTP report write.
- 429: per-worker job capacity is full; Retry-After is one second.
- 503: credentials are unconfigured or persisted policy/storage is unavailable.
- 500: unexpected processing error; response and application logs exclude the exception's raw detail.

Every application response gets a generated request ID and `Cache-Control: no-store`. Configure the `fusion.api` logger at INFO to collect route-template, status and duration fields. These logs are instrumentation, not an operated alerting/monitoring system.

## Recovery procedures

1. **Invalid update:** the active policy is unchanged; repair and validate the candidate.
2. **Concurrent update conflict:** reread `/policy/version`, inspect the intervening change, then deliberately retry with its revision. Do not blindly overwrite it.
3. **Policy rollback:** submit the previously approved policy text against the current revision. It becomes a new audited revision; do not edit database rows manually.
4. **Restart:** reconnect to the same database. Retained decisions, filtered nodes and audit events remain available. The default retention is the latest 500 decisions; older decisions return 404.
5. **Corrupt/unavailable database:** readiness fails closed. Preserve the damaged file for investigation and restore a trusted backup offline. The service does not silently reset policy to defaults.
6. **Backup:** use SQLite's online backup interface or stop the service and copy a consistent database. Copying only the main database during WAL writes is not a safe backup procedure.

Policy history has no automated archival policy yet. Production use needs disk-capacity monitoring and tested backup/restore procedures. Checksums detect accidental policy corruption; an attacker able to rewrite both policy and checksum is outside this mechanism. The audit is transactional, not cryptographically tamper-proof.

## Unverified deployment concerns

No internet deployment, TCP/TLS load test, multi-host failover, identity-provider integration, independent penetration test or real-user service-level objective has been demonstrated. In-process ASGI performance numbers exclude the network and reverse proxy. Request admission does not forcibly cancel a CPU-bound job after a client disconnects.
