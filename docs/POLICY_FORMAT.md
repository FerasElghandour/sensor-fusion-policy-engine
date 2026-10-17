# Policy File Format

Policies are YAML (or JSON — YAML is a superset) files validated against
`fusion_compliance_loop/policy_schema.py` (`PolicyFile` / `PolicyRuleSpec`,
pydantic models). No rule logic lives in Python — the engine
(`fusion_compliance_loop/policy_engine.py`) only interprets these declarative
fields. See [policies/default_policy.yaml](../policies/default_policy.yaml)
for the shipped, complete example, and
[policies/alt_policy_v1_1.yaml](../policies/alt_policy_v1_1.yaml) for a
worked "policy update" example.

## Top-level fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `policy_id` | string | yes | Identifier for this policy artifact (shown on every decision it produces). |
| `policy_version` | string | yes | Version of the whole file (e.g. `"1.0.0"`). |
| `field_sensitivity_map` | map of field name → classification level | no | Declares the *true* sensitivity of specific fields, independent of what an item's own `classification_level` claims. Used by rules with `check_field_sensitivity_mismatch: true`. |
| `rules` | list of rule objects | yes, ≥1 | Evaluated in ascending `rule_priority` order; the first rule whose conditions all hold wins. |

**Validation invariants** (enforced at load time, in `PolicyFile`):
- At least one rule.
- At least one *unconditional catch-all* rule — no `classification_level`,
  `source_domain`, `destination_domain`, `sensor_type` constraint,
  `release_authority` left as `"any"`, and `check_field_sensitivity_mismatch`
  false. This guarantees evaluation never falls through with no decision.
- `rule_id` values are unique within the file.

## Rule fields

| Field | Type | Meaning |
|---|---|---|
| `rule_id` | string | Unique name for the rule; appears as `rule_name` on every `PolicyDecision` it produces. |
| `rule_version` | string | Version of this specific rule (independent of `policy_version`). |
| `rule_priority` | int | Lower runs first. The shipped default policy uses 10, 20, 30, 40, 50, 100 to leave room for insertions. |
| `effective_date` | date (`YYYY-MM-DD`) | The rule only matches on or after this date (compared against real UTC "today" unless an `as_of` override is passed to `PolicyEngine.evaluate()`). |
| `description` | string | Free text, folded into the generated plain-English explanation. |
| `classification_level` | list of `public`\|`sensitive`\|`restricted`\|`protected_b`\|`confidential`, or omitted | If present, the item's `classification_level` must be in this list. `protected_b` is a **synthetic stand-in label** — no real Protected B data, systems, or accreditation are used or implied (see application/EVIDENCE_GAPS.md). |
| `source_domain` | list of network domains (`open`\|`partner`\|`internal`\|`restricted_net`\|`canada_protected`\|`coalition_unclassified`), or omitted | If present, the item's own `network_domain` must be in this list. The last two are explicit, simulated network security domains added to demonstrate essential outcome #2. |
| `destination_domain` | list of network domains, or omitted | If present, the domain being requested (the fusion target) must be in this list. |
| `sensor_type` | list of `camera`\|`radar`, or omitted | If present, the item's `sensor_source` must be in this list. |
| `release_authority` | `any` \| `not_granted_for_destination` \| `empty` \| `declared_but_missing_destination` | See table below. |
| `check_field_sensitivity_mismatch` | bool | If true, the rule only matches when some field in `field_sensitivity_map` is populated on the item **and** the item's declared `classification_level` is lower than that field's true sensitivity — regardless of what the item's own label claims. |
| `requires_downgrade_authorization` | bool | If true, the rule only matches when the item carries a non-empty `downgrade_authorized_by` (an accountability marker — see `AUTHORIZED_PROTECTED_B_DOWNGRADE` in the default policy). Lets a policy state "authorized downgrade actions require a specific machine-readable rule and accountability record" precisely. |
| `requires_ai_risk_at_least` | float (0-1), or omitted | If present, the rule only matches when the AI compliance-risk score passed to `PolicyEngine.evaluate(..., ai_risk_score=...)` is at least this value. The AI can only make this *condition* true or false — it never sets `enforcement_action` itself. See `docs/MODEL_CARD.md` and `AI_HIGH_RISK_REVIEW` in the default policy. |
| `enforcement_action` | `PERMIT`\|`RESTRICT`\|`SEGREGATE`\|`REJECT`\|`REQUIRE_REVIEW`\|`DOWNGRADE` | What happens when this rule matches. `DOWNGRADE` is distinct from `RESTRICT`: it represents an explicit, accountable reclassification-to-lower-sensitivity action, and (in the shipped default policy) only ever fires alongside `requires_downgrade_authorization: true`. |
| `permitted_fields` | list of field names | Documentation of what's expected to flow through; not independently enforced (the complement of `restricted_fields`/mismatch fields is permitted by construction). |
| `restricted_fields` | list of field names, or `["*"]` | Fields blocked (set to null) when this rule matches. `["*"]` blocks the entire item (used by `REJECT`). Ignored for rules with `check_field_sensitivity_mismatch: true`, which compute blocked fields dynamically from the mismatch itself. |
| `required_metadata` | list of field names | If non-empty, the rule only matches when **all** listed fields are non-null on the item. Lets a rule refuse to fire on incomplete data rather than guessing. |

### `release_authority` modes

| Mode | Matches when |
|---|---|
| `any` | No constraint (default). |
| `not_granted_for_destination` | The destination domain is **not** in the item's `release_permissions` — including when that list is empty. |
| `empty` | `release_permissions` is exactly `[]`. |
| `declared_but_missing_destination` | `release_permissions` is non-empty, but doesn't include the destination domain (distinguishes "explicitly scoped elsewhere" from "never filled in at all"). |

## Loading and reloading

```python
from fusion_compliance_loop.policy_engine import PolicyEngine

engine = PolicyEngine()                      # loads policies/default_policy.yaml
engine = PolicyEngine(policy_path="my.yaml") # or an explicit path

engine.reload_from_path("updated.yaml")      # validate-then-swap
engine.reload_from_text(yaml_or_json_string) # same, from an in-memory string
```

`reload_from_text`/`reload_from_path` fully parse and validate the candidate
**before** touching `engine.policy`. On any failure they raise
`PolicyLoadError` and the active policy is left exactly as it was — this is
what the "invalid policy reloads must preserve the last valid policy"
acceptance test verifies (`tests/test_policy_loader.py`,
`tests/test_v02_acceptance.py`).

Over HTTP: `GET /policy/version`, `POST /policy/validate` (dry run, no
mutation), `POST /policy/reload` (422 with the validation error on failure,
policy unchanged). Both POST routes require admin credentials. Reload also
requires `expected_revision`; stale writers receive 409. Read routes require
reader/admin credentials. See [OPERATIONS.md](OPERATIONS.md).

## The shipped default policy's rules (priority order)

1. `FORBIDDEN_DOMAIN` (10) — CONFIDENTIAL, not released → REJECT (whole item).
2. `AUTHORIZED_PROTECTED_B_DOWNGRADE` (15) — Protected B, not released, **and** an explicit downgrade authorization is on file → DOWNGRADE (sensitive field stripped, rest crosses, authorizer named in the explanation as an accountability record).
3. `RESTRICTED_CROSS_DOMAIN` (20) — RESTRICTED, not released → SEGREGATE.
4. `PROTECTED_B_CROSS_DOMAIN` (25) — Protected B, not released, **no** authorization on file → SEGREGATE (an unauthorized downgrade attempt falls through to here, never to a full PERMIT/DOWNGRADE).
5. `SENSITIVE_MASKING` (30) — SENSITIVE, permissions declared elsewhere but not here → RESTRICT.
6. `MISCLASSIFIED_FIELD` (40) — declared classification lower than a field's true sensitivity → REQUIRE_REVIEW.
7. `MISSING_RELEASE_PERMISSION` (50) — no release permissions on file at all, not PUBLIC → REQUIRE_REVIEW.
8. `AI_HIGH_RISK_REVIEW` (90) — AI compliance-risk score ≥ 0.85 and no higher-priority rule already matched → REQUIRE_REVIEW.
9. `DEFAULT_PERMIT` (100) — everything else → PERMIT.

## Every decision is fully attributed

`PolicyEngine.evaluate()`/`.apply()` return a `PolicyDecision` carrying:
`data_id`, `action`, `rule_name`, `blocked_fields`, `explanation` (a `reason`
property aliases this), `policy_id`, `policy_version`, `rule_version`, and
`timestamp`. Nothing is decided anonymously.


## Additional validation in the local engineering revision

Unknown schema keys and unknown sensor field names are rejected rather than
silently ignored. Risk thresholds must be within [0, 1]. YAML aliases and
policy text larger than 60,000 bytes are rejected. At least one currently
effective catch-all must also have no metadata-presence condition.

`PolicyEngine.policy` returns a detached copy. A `FusionEngine` pins a policy
snapshot when constructed for a mission; changing its shared source engine
cannot mix camera/radar decisions from different policy versions.
