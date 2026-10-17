from typing import Callable, Optional

from .active_sensor_request_planner import SensorRequestPlanner
from .audit_log_exporter import log_event
from .compliance_engine import ComplianceEngine
from .entity_association_engine import rank_candidates
from .enums import NetworkDomain
from .evidence_dependency_graph import EvidenceDependencyGraph
from .downstream_fusion import DownstreamFusionPipeline
from .models import CameraDetection, FusionResult, MatchCandidate, RadarDetection
from .policy_engine import PolicyEngine
from .provenance_recorder import ProvenanceRecorder


class FusionEngine:
    """Orchestrates the loop: Fusion Compliance Engine inspects camera ->
    request missing evidence -> Fusion Compliance Engine inspects every
    radar candidate independently -> associate -> reference downstream
    fusion pipeline fuses confidence (approved data only) -> record
    provenance. See compliance_engine.py and downstream_fusion.py for the
    two separately-owned pieces this class orchestrates; see
    application/TECHNICAL_CONCEPT.md for the corrected system-boundary
    diagram this class implements."""

    def __init__(
        self,
        network_domain: NetworkDomain = NetworkDomain.OPEN,
        max_sensor_requests: int = 3,
        policy_engine: Optional[PolicyEngine] = None,
        use_ai_risk: bool = True,
    ):
        """policy_engine lets a caller share one PolicyEngine instance across
        many FusionEngine.run() calls (e.g. a benchmark batch) so a live
        reload takes effect on the next mission without recreating anything.
        use_ai_risk controls only the FCE's AI compliance-risk detector
        (ai_compliance_risk.py) — separate from use_ai_association on run(),
        which controls the *reference fusion pipeline's* entity-association
        scorer. Both default on; both can be disabled independently."""
        self.network_domain = network_domain
        self.planner = SensorRequestPlanner(max_requests=max_sensor_requests)
        self.policy = (policy_engine or PolicyEngine()).snapshot()
        self.dependency_graph = EvidenceDependencyGraph()
        self.provenance = ProvenanceRecorder()
        self.compliance = ComplianceEngine(policy_engine=self.policy, provenance=self.provenance, use_ai_risk=use_ai_risk)
        self.downstream = DownstreamFusionPipeline(self.dependency_graph)

    def run(
        self,
        camera: CameraDetection,
        radar_pool_fn: Callable[[], list[RadarDetection]],
        use_ai_association: bool = False,
        ai_model=None,
    ) -> FusionResult:
        """use_ai_association=False (default) reproduces the original
        deterministic-only behaviour exactly. When True, candidate ranking
        is delegated to the AI model (ai_entity_association.ai_rank_candidates)
        instead of the deterministic scorer — but everything downstream of
        picking a "best" candidate (policy application, confidence fusion,
        provenance) is identical code, so the AI can never bypass compliance.

        Every item — the camera detection AND every radar candidate — is
        independently inspected by self.compliance (the Fusion Compliance
        Engine) before any of it reaches self.downstream (the reference
        fusion pipeline). A rejected camera item stops here; a rejected
        radar candidate simply never contributes, without changing which
        candidate was selected."""
        log_event(self.provenance.conn, "OBSERVATION", f"Camera {camera.id} reported a possible {camera.object_class.value} at {camera.confidence_score:.0%} confidence.")

        camera_disposition = self.compliance.inspect(camera, self.network_domain)
        self.dependency_graph.register(camera_disposition.filtered_item)

        if not camera_disposition.approved:
            explanation = (
                f"Camera detection {camera.id} was blocked by the Fusion Compliance Engine "
                f"before it could reach the fusion pipeline. {camera_disposition.policy_decision.explanation}"
            )
            result = FusionResult(
                object_class=camera.object_class,
                confidence_before=camera.confidence_score,
                confidence_after=camera.confidence_score,
                contributing_data_ids=[],
                blocked_fields=list(camera_disposition.policy_decision.blocked_fields),
                applied_policy_rules=[],
                requested_evidence=[],
                candidates_considered=[],
                explanation=explanation,
                camera_compliance_decision_id=camera_disposition.compliance_decision_id,
                camera_policy_rule=f"{camera_disposition.policy_decision.rule_name}:{camera_disposition.policy_decision.action.value}",
                camera_policy_id=camera_disposition.policy_decision.policy_id,
                camera_policy_version=camera_disposition.policy_decision.policy_version,
                camera_blocked_fields=list(camera_disposition.policy_decision.blocked_fields),
                camera_ai_risk_probability=camera_disposition.ai_risk.risk_probability,
                camera_approved=False,
                radar_dispositions=[],
            )
            # contributing_data_ids stays [] (no data was permitted to feed a
            # fused confidence value) but the provenance trace must still
            # include the camera — the conclusion IS the record of what the
            # FCE decided about that exact input, even though the decision
            # was "block it."
            self.provenance.record_conclusion(result, [camera.id])
            log_event(self.provenance.conn, "CONCLUSION", result.explanation)
            return result

        camera_item = camera_disposition.filtered_item

        requested_evidence: list[str] = []
        blocked_fields_total: list[str] = []
        applied_rules: list[str] = []
        contributing_ids: list[str] = [camera.id]
        candidates_considered = []
        radar_disposition_summaries: list[dict] = []
        confidence_after = camera.confidence_score

        missing = self.planner.missing_fields(camera_item)
        if missing:
            sensor_needed = self.planner.request(missing)
            requested_evidence.extend(self.planner.request_log)
            for line in self.planner.request_log[-1:]:
                log_event(self.provenance.conn, "EVIDENCE_REQUEST", line)

            if sensor_needed is not None:
                radar_candidates = radar_pool_fn()

                # Fusion Compliance Engine inspects EVERY radar candidate
                # independently — not just the one association eventually
                # selects. This is what "the compliance engine must inspect
                # every incoming sensor item before any data reaches the
                # downstream fusion process" means in code.
                radar_dispositions_by_id = {}
                for r in radar_candidates:
                    disp = self.compliance.inspect(r, self.network_domain)
                    radar_dispositions_by_id[r.id] = disp
                    radar_disposition_summaries.append(disp.summary())
                    self.dependency_graph.register(disp.filtered_item)

                # Ranking runs on the RAW candidate pool, exactly as before —
                # it never reads the one field any rule ever blocks
                # (raw_signal_signature), so this carries no leakage risk
                # (see docs/THREAT_MODEL.md), and preserves the existing,
                # tested guarantee that a rejected top candidate is never
                # silently replaced by the next-best one.
                if use_ai_association:
                    candidates_considered = self._ai_rank(camera_item, radar_candidates, ai_model)
                else:
                    candidates_considered = rank_candidates(camera_item, radar_candidates)
                best = candidates_considered[0] if candidates_considered else None
                log_event(
                    self.provenance.conn,
                    "ASSOCIATION",
                    f"Ranked {len(candidates_considered)} radar candidate(s); best match "
                    f"{best.radar_id if best else 'none'} scored {best.association_score if best else 0:.3f}.",
                )

                if best is not None:
                    winning_disposition = radar_dispositions_by_id[best.radar_id]
                    decision = winning_disposition.policy_decision
                    applied_rules.append(f"{decision.rule_name}:{decision.action.value}")
                    blocked_fields_total.extend(decision.blocked_fields)
                    log_event(self.provenance.conn, "POLICY_DECISION", decision.explanation, rule_name=decision.rule_name)

                    if winning_disposition.approved:
                        outcome = self.downstream.fuse(camera_disposition, winning_disposition)
                        confidence_after = outcome.confidence_after
                        contributing_ids.append(winning_disposition.item_id)
                        log_event(self.provenance.conn, "CONFIDENCE_FUSION", outcome.explanation)

        result = FusionResult(
            object_class=camera_item.object_class,
            confidence_before=camera.confidence_score,
            confidence_after=confidence_after,
            contributing_data_ids=contributing_ids,
            blocked_fields=blocked_fields_total,
            applied_policy_rules=applied_rules,
            requested_evidence=requested_evidence,
            candidates_considered=candidates_considered,
            explanation=self._explain(camera_item, confidence_after, applied_rules, blocked_fields_total),
            camera_compliance_decision_id=camera_disposition.compliance_decision_id,
            camera_policy_rule=f"{camera_disposition.policy_decision.rule_name}:{camera_disposition.policy_decision.action.value}",
            camera_policy_id=camera_disposition.policy_decision.policy_id,
            camera_policy_version=camera_disposition.policy_decision.policy_version,
            camera_blocked_fields=list(camera_disposition.policy_decision.blocked_fields),
            camera_ai_risk_probability=camera_disposition.ai_risk.risk_probability,
            camera_approved=True,
            radar_dispositions=radar_disposition_summaries,
        )
        self.provenance.record_conclusion(result, contributing_ids)
        log_event(self.provenance.conn, "CONCLUSION", result.explanation)
        return result

    @staticmethod
    def _ai_rank(camera: CameraDetection, radar_candidates: list[RadarDetection], ai_model) -> list[MatchCandidate]:
        from .ai_entity_association import ai_rank_candidates

        ranked = ai_rank_candidates(camera, radar_candidates, model=ai_model)
        return [
            MatchCandidate(
                radar_id=radar.id,
                camera_id=camera.id,
                association_score=prediction.match_probability,
                rationale="AI model: " + "; ".join(prediction.explanation),
            )
            for radar, prediction, _features in ranked
        ]

    @staticmethod
    def _explain(camera: CameraDetection, confidence_after: float, applied_rules: list[str], blocked_fields: list[str]) -> str:
        parts = [
            f"Camera detected a possible {camera.object_class.value} with {camera.confidence_score:.0%} confidence."
        ]
        if applied_rules:
            parts.append(f"Policy rules applied: {', '.join(applied_rules)}.")
        if blocked_fields:
            parts.append(f"Fields excluded from fusion: {', '.join(blocked_fields)}.")
        parts.append(f"Final fused confidence: {confidence_after:.0%}.")
        return " ".join(parts)
