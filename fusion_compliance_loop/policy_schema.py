"""Pydantic schema for external, machine-readable policy files (YAML/JSON).

A policy file is data, not code: it can be edited, versioned, and reloaded
without touching the Python engine. See docs/POLICY_FORMAT.md for the field
reference and worked examples.
"""

from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import ClassificationLevel, NetworkDomain, PolicyAction, SensorType
from .models import CameraDetection, RadarDetection

KNOWN_FIELDS = set(CameraDetection.model_fields) | set(RadarDetection.model_fields)

# How a rule's `release_authority` condition is evaluated against the item's
# own declared release_permissions and the requested destination domain.
ReleaseAuthorityMode = Literal[
    "any",  # no constraint
    "not_granted_for_destination",  # destination_domain not in item.release_permissions
    "empty",  # item.release_permissions == []
    "declared_but_missing_destination",  # release_permissions non-empty, but doesn't include destination
]


class PolicyRuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    rule_version: str = Field(min_length=1)
    rule_priority: int = Field(description="Lower runs first; first matching rule wins.")
    effective_date: date
    description: str = ""

    # Match conditions — every non-null field below must hold for the rule to apply.
    classification_level: Optional[list[ClassificationLevel]] = None
    source_domain: Optional[list[NetworkDomain]] = None
    destination_domain: Optional[list[NetworkDomain]] = None
    sensor_type: Optional[list[SensorType]] = None
    release_authority: ReleaseAuthorityMode = "any"
    check_field_sensitivity_mismatch: bool = False
    # Only matches if the item carries an explicit downgrade authorization
    # marker (DataItem.downgrade_authorized_by is truthy) — see
    # docs/POLICY_FORMAT.md. Lets a policy state "authorized downgrade
    # actions require a specific machine-readable rule and accountability
    # record" without ever letting an unauthorized item match this rule.
    requires_downgrade_authorization: bool = False
    # Only matches if the AI compliance-risk score for this item is >= this
    # value. The AI can only ever make this condition true or false — it
    # never sets enforcement_action itself, and this condition can only be
    # attached to rules the policy author chooses to write (e.g. escalating
    # an otherwise-PERMIT case to REQUIRE_REVIEW/SEGREGATE). None means the
    # rule does not depend on the AI risk score at all.
    requires_ai_risk_at_least: Optional[float] = Field(default=None, ge=0, le=1)

    # Effect
    enforcement_action: PolicyAction
    permitted_fields: list[str] = Field(default_factory=list)
    restricted_fields: list[str] = Field(default_factory=list)
    required_metadata: list[str] = Field(default_factory=list)

    @field_validator("rule_id", "rule_version")
    @classmethod
    def rule_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rule_id must not be blank")
        return v

    @field_validator("restricted_fields", "permitted_fields", "required_metadata")
    @classmethod
    def field_names_exist(cls, values: list[str]) -> list[str]:
        if set(values) - KNOWN_FIELDS - {"*"}:
            raise ValueError("policy references an unknown sensor field")
        return values


class PolicyFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    field_sensitivity_map: dict[str, ClassificationLevel] = Field(default_factory=dict)
    rules: list[PolicyRuleSpec]

    @field_validator("policy_id", "policy_version")
    @classmethod
    def identifiers_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("policy identifiers must not be blank")
        return value

    @field_validator("field_sensitivity_map")
    @classmethod
    def sensitivity_fields_exist(cls, values):
        if set(values) - KNOWN_FIELDS:
            raise ValueError("sensitivity map references an unknown sensor field")
        return values

    @field_validator("rules")
    @classmethod
    def must_have_at_least_one_rule(cls, rules: list[PolicyRuleSpec]) -> list[PolicyRuleSpec]:
        if not rules:
            raise ValueError("policy file must define at least one rule")
        return rules

    @field_validator("rules")
    @classmethod
    def must_have_catchall_rule(cls, rules: list[PolicyRuleSpec]) -> list[PolicyRuleSpec]:
        """At least one rule must be able to match unconditionally (no
        classification/domain/sensor/release constraint), so evaluation can
        never fall through with no decision."""
        has_catchall = any(
            r.classification_level is None
            and r.source_domain is None
            and r.destination_domain is None
            and r.sensor_type is None
            and r.release_authority == "any"
            and not r.check_field_sensitivity_mismatch
            and not r.requires_downgrade_authorization
            and r.requires_ai_risk_at_least is None
            and not r.required_metadata
            and r.effective_date <= datetime.now(timezone.utc).date()
            for r in rules
        )
        if not has_catchall:
            raise ValueError("policy file must define at least one unconditional catch-all rule")
        return rules

    @field_validator("rules")
    @classmethod
    def rule_ids_unique(cls, rules: list[PolicyRuleSpec]) -> list[PolicyRuleSpec]:
        ids = [r.rule_id for r in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule_id values must be unique within a policy file")
        return rules
