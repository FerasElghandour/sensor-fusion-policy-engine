"""Policy engine driven entirely by external, machine-readable policy files
(YAML/JSON — see policies/default_policy.yaml and docs/POLICY_FORMAT.md).

No rule logic lives in Python: the engine loads a PolicyFile, sorts its rules
by priority, and evaluates each item's fields against the declarative match
conditions. Reloading a policy validates the candidate file completely before
swapping it in — an invalid file never touches the active policy.
"""

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional, Union
from threading import RLock
import json

import yaml
from pydantic import ValidationError

from .enums import CLASSIFICATION_ORDER, ClassificationLevel, NetworkDomain
from .models import DataItem, PolicyDecision
from .policy_schema import PolicyFile, PolicyRuleSpec

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "policies" / "default_policy.yaml"


class PolicyLoadError(Exception):
    """Raised when a candidate policy file fails to parse or validate.
    Callers can rely on the active policy being untouched when this is raised."""


def load_policy_text(text: str) -> PolicyFile:
    try:
        if len(text.encode("utf-8")) > 60000:
            raise PolicyLoadError("policy text exceeds 60000 bytes")
        try:
            # Persisted revisions are canonical JSON. Avoid repeatedly running
            # the YAML scanner/parser on every authenticated API request.
            raw = json.loads(text)
        except json.JSONDecodeError:
            if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(text)):
                raise PolicyLoadError("YAML aliases are not supported in policy files")
            raw = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError) as exc:
        raise PolicyLoadError(f"could not parse policy file as YAML/JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyLoadError("policy file must be a mapping at the top level")
    try:
        policy = PolicyFile.model_validate(raw)
    except ValidationError as exc:
        raise PolicyLoadError(f"policy file failed schema validation: {exc}") from exc
    policy.rules = sorted(policy.rules, key=lambda r: r.rule_priority)
    return policy


def load_policy_path(path: Union[str, Path]) -> PolicyFile:
    text = Path(path).read_text()
    return load_policy_text(text)


def _field_sensitivity_mismatch(item: DataItem, field_sensitivity_map: dict[str, ClassificationLevel]) -> bool:
    return bool(_mismatched_fields(item, field_sensitivity_map))


def _mismatched_fields(item: DataItem, field_sensitivity_map: dict[str, ClassificationLevel]) -> list[str]:
    return [
        f
        for f, true_level in field_sensitivity_map.items()
        if getattr(item, f, None) is not None
        and CLASSIFICATION_ORDER.index(item.classification_level) < CLASSIFICATION_ORDER.index(true_level)
    ]


def _rule_matches(
    rule: PolicyRuleSpec,
    item: DataItem,
    target_domain: NetworkDomain,
    field_sensitivity_map: dict[str, ClassificationLevel],
    as_of: date,
    ai_risk_score: Optional[float] = None,
) -> bool:
    if rule.effective_date > as_of:
        return False
    if rule.classification_level is not None and item.classification_level not in rule.classification_level:
        return False
    if rule.source_domain is not None and item.network_domain not in rule.source_domain:
        return False
    if rule.destination_domain is not None and target_domain not in rule.destination_domain:
        return False
    if rule.sensor_type is not None and item.sensor_source not in rule.sensor_type:
        return False

    if rule.release_authority == "not_granted_for_destination":
        if target_domain in item.release_permissions:
            return False
    elif rule.release_authority == "empty":
        if item.release_permissions:
            return False
    elif rule.release_authority == "declared_but_missing_destination":
        if not item.release_permissions or target_domain in item.release_permissions:
            return False
    # "any" -> no release_authority constraint

    if rule.check_field_sensitivity_mismatch and not _field_sensitivity_mismatch(item, field_sensitivity_map):
        return False

    if rule.required_metadata and any(getattr(item, f, None) is None for f in rule.required_metadata):
        return False

    if rule.requires_downgrade_authorization and not item.downgrade_authorized_by:
        return False

    if rule.requires_ai_risk_at_least is not None:
        if ai_risk_score is None or ai_risk_score < rule.requires_ai_risk_at_least:
            return False

    return True


def _blocked_fields_for(rule: PolicyRuleSpec, item: DataItem, field_sensitivity_map: dict[str, ClassificationLevel]) -> list[str]:
    if rule.check_field_sensitivity_mismatch:
        return _mismatched_fields(item, field_sensitivity_map)
    if "*" in rule.restricted_fields:
        return ["*"]
    return [f for f in rule.restricted_fields if getattr(item, f, None) is not None]


def _explain(
    rule: PolicyRuleSpec,
    item: DataItem,
    target_domain: NetworkDomain,
    blocked: list[str],
    ai_risk_score: Optional[float] = None,
) -> str:
    if rule.description.strip():
        detail = rule.description.strip().rstrip(".")
    else:
        detail = f"rule {rule.rule_id} applied"
    blocked_note = f" Blocked field(s): {blocked}." if blocked else ""
    accountability_note = (
        f" Downgrade authorized by: {item.downgrade_authorized_by} (accountability record)."
        if rule.enforcement_action.value == "DOWNGRADE"
        else ""
    )
    ai_note = (
        f" Escalated by AI compliance-risk signal (score {ai_risk_score:.2f} >= threshold "
        f"{rule.requires_ai_risk_at_least:.2f})."
        if rule.requires_ai_risk_at_least is not None and ai_risk_score is not None
        else ""
    )
    return (
        f"Item {item.id} is classified {item.classification_level.value} and was evaluated against the "
        f"{target_domain.value} domain. {detail}.{blocked_note}{accountability_note}{ai_note}"
    )


class PolicyEngine:
    """Loads a policy file once at construction and evaluates every item
    against it. Call reload_from_path()/reload_from_text() to swap policies
    at runtime — the swap only happens if the candidate validates cleanly."""

    def __init__(self, policy_path: Optional[Union[str, Path]] = None):
        self._policy_path = Path(policy_path) if policy_path else DEFAULT_POLICY_PATH
        self._lock = RLock()
        self._policy: PolicyFile = load_policy_path(self._policy_path)

    @classmethod
    def from_text(cls, text: str) -> "PolicyEngine":
        instance = cls.__new__(cls)
        instance._policy_path = None
        instance._lock = RLock()
        instance._policy = load_policy_text(text)
        return instance

    @property
    def policy(self) -> PolicyFile:
        # A caller cannot mutate active rules without schema validation.
        with self._lock:
            return self._policy.model_copy(deep=True)

    def snapshot(self) -> "PolicyEngine":
        """Detached policy for one mission, unaffected by concurrent reloads."""
        instance = self.__class__.__new__(self.__class__)
        instance._policy_path = self._policy_path
        instance._lock = RLock()
        with self._lock:
            instance._policy = self._policy.model_copy(deep=True)
        return instance

    @property
    def policy_id(self) -> str:
        return self.policy.policy_id

    @property
    def policy_version(self) -> str:
        return self.policy.policy_version

    @property
    def rule_count(self) -> int:
        return len(self.policy.rules)

    def reload_from_text(self, text: str) -> PolicyFile:
        """Validate-then-swap: the candidate is fully parsed and validated
        before self.policy is touched. On failure this raises PolicyLoadError
        and the active policy is left exactly as it was."""
        candidate = load_policy_text(text)
        with self._lock:
            self._policy = candidate
        return candidate.model_copy(deep=True)

    def reload_from_path(self, path: Union[str, Path]) -> PolicyFile:
        return self.reload_from_text(Path(path).read_text())

    def evaluate(
        self,
        item: DataItem,
        target_domain: NetworkDomain,
        as_of: Optional[date] = None,
        ai_risk_score: Optional[float] = None,
    ) -> PolicyDecision:
        """ai_risk_score, when supplied, lets a rule's requires_ai_risk_at_least
        condition match — but it is just one more declarative condition
        evaluated in the same fixed rule_priority order as everything else.
        The AI never sets `enforcement_action`; it can only make an
        AI-conditioned rule eligible to match, and only rules a human policy
        author chose to write that way."""
        as_of = as_of or datetime.now(timezone.utc).date()
        with self._lock:
            policy = self._policy
        for rule in policy.rules:
            if _rule_matches(rule, item, target_domain, policy.field_sensitivity_map, as_of, ai_risk_score):
                blocked = _blocked_fields_for(rule, item, policy.field_sensitivity_map)
                return PolicyDecision(
                    data_id=item.id,
                    action=rule.enforcement_action,
                    rule_name=rule.rule_id,
                    blocked_fields=blocked,
                    explanation=_explain(rule, item, target_domain, blocked, ai_risk_score),
                    policy_id=policy.policy_id,
                    policy_version=policy.policy_version,
                    rule_version=rule.rule_version,
                    timestamp=datetime.now(timezone.utc),
                )
        raise RuntimeError("no rule matched — a validated policy file always has a catch-all rule")

    def apply(
        self,
        item: DataItem,
        target_domain: NetworkDomain,
        as_of: Optional[date] = None,
        ai_risk_score: Optional[float] = None,
    ) -> tuple[DataItem, PolicyDecision]:
        decision = self.evaluate(item, target_domain, as_of=as_of, ai_risk_score=ai_risk_score)
        filtered = item.model_copy(deep=True)
        for field_name in decision.blocked_fields:
            if field_name != "*" and hasattr(filtered, field_name):
                setattr(filtered, field_name, None)
        filtered.transformation_history.append(f"policy:{decision.rule_name}:{decision.action.value}")
        return filtered, decision
