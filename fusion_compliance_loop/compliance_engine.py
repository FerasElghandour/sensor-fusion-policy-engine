"""The Fusion Compliance Engine (FCE) itself.

Per the official challenge text (application/OFFICIAL_CHALLENGE_REQUIREMENTS.md):
"DND/CAF requires an automated compliance layer that sits between raw
sensor ingestion and the fusion analytics pipeline." This module IS that
layer. It inspects one item at a time — camera or radar, independently —
and produces a ComplianceDisposition: an AI compliance-risk assessment, a
deterministic policy decision, field-level filtering, a provenance record,
and an audit record. Nothing downstream (see downstream_fusion.py) may
consume a raw sensor item directly; it may only consume an approved
ComplianceDisposition emitted here.

The enforcement sequence is always:
    AI identifies compliance risk -> deterministic policy engine evaluates
    rules -> this engine records the resulting disposition.
The AI's risk_probability can make an AI-conditioned rule (requires_ai_risk_at_least
in policy_schema.py) eligible to match, but the deterministic PolicyEngine
still runs its full, fixed-priority rule evaluation every time — the AI
never sets `enforcement_action` and never bypasses a rule that already
matched at higher priority. See docs/MODEL_CARD.md and
application/TECHNICAL_CONCEPT.md for the full architecture.
"""

from dataclasses import dataclass, field
from typing import Optional

from .ai_compliance_risk import ComplianceRiskModel, get_default_risk_model
from .audit_log_exporter import log_event
from .enums import NetworkDomain, PolicyAction
from .models import ComplianceRiskAssessment, DataItem, PolicyDecision, new_id
from .policy_engine import PolicyEngine
from .provenance_recorder import ProvenanceRecorder


@dataclass
class ComplianceDisposition:
    """The FCE's complete, per-item verdict. A plain dataclass (not a
    Pydantic model) so `filtered_item` can hold either a CameraDetection or
    RadarDetection instance without risking subclass-field truncation on
    validation — see the design note in models.py history for why."""

    compliance_decision_id: str
    item_id: str
    approved: bool
    filtered_item: DataItem
    policy_decision: PolicyDecision
    ai_risk: ComplianceRiskAssessment
    sensor_source: str = ""

    def summary(self) -> dict:
        """A small, JSON-safe summary used by FusionResult.radar_dispositions
        and by API/dashboard surfaces — never the full item payload."""
        return {
            "compliance_decision_id": self.compliance_decision_id,
            "item_id": self.item_id,
            "sensor_source": self.sensor_source,
            "approved": self.approved,
            "action": self.policy_decision.action.value,
            "rule_name": self.policy_decision.rule_name,
            "policy_id": self.policy_decision.policy_id,
            "policy_version": self.policy_decision.policy_version,
            "blocked_fields": list(self.policy_decision.blocked_fields),
            "ai_risk_probability": self.ai_risk.risk_probability,
            "ai_risk_categories": list(self.ai_risk.risk_categories),
            "explanation": self.policy_decision.explanation,
        }


class ComplianceEngine:
    """Inspects one item at a time. Camera and radar items are gated through
    the exact same path, independently — this is the fix for essential
    outcome #2's "at least two sensor modalities" requirement."""

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        risk_model: Optional[ComplianceRiskModel] = None,
        provenance: Optional[ProvenanceRecorder] = None,
        use_ai_risk: bool = True,
    ):
        self.policy = policy_engine or PolicyEngine()
        self.risk_model = risk_model or get_default_risk_model()
        self.provenance = provenance or ProvenanceRecorder()
        self.use_ai_risk = use_ai_risk

    def inspect(self, item: DataItem, target_domain: NetworkDomain) -> ComplianceDisposition:
        """Metadata validation + AI risk assessment + deterministic policy
        decision + field-level filtering + provenance + audit, for exactly
        one item. Never mutates `item` — the filtered copy is separate."""
        if self.use_ai_risk:
            ai_risk = self.risk_model.assess(item, self.policy.policy.field_sensitivity_map, target_domain)
        else:
            ai_risk = ComplianceRiskAssessment(
                risk_probability=0.0,
                risk_categories=[],
                contributing_factors=[],
                confidence=0.0,
                explanation="AI compliance-risk assessment was disabled for this inspection.",
            )

        filtered_item, decision = self.policy.apply(item, target_domain, ai_risk_score=ai_risk.risk_probability)
        approved = decision.action != PolicyAction.REJECT

        # Persist only the filtered item. Writing raw data first and then
        # overwriting it can leave restricted values in a database journal.
        self.provenance.record(filtered_item, retain_payload=approved)

        log_event(self.provenance.conn, "COMPLIANCE_DECISION", decision.explanation, rule_name=decision.rule_name)
        if ai_risk.risk_categories:
            log_event(self.provenance.conn, "AI_COMPLIANCE_RISK", ai_risk.explanation)

        return ComplianceDisposition(
            compliance_decision_id=new_id(),
            item_id=item.id,
            approved=approved,
            filtered_item=filtered_item,
            policy_decision=decision,
            ai_risk=ai_risk,
            sensor_source=item.sensor_source.value,
        )
