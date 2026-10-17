"""Reference downstream fusion pipeline — explicitly NOT the proposed Fusion
Compliance Engine (see compliance_engine.py).

Per the official challenge text, DND/CAF is not asking for the main
sensor-fusion platform: "We are not proposing the main sensor-fusion
platform" — the FCE "sits between raw sensor ingestion and the fusion
analytics pipeline." This module stands in for that existing/downstream
pipeline in this repository, so the FCE has something realistic to gate.

Its one structural rule: it will not accept anything except an *approved*
ComplianceDisposition, produced by ComplianceEngine.inspect(). This is
enforced in code, not by convention — see _require_approved below.
"""

from dataclasses import dataclass

from .compliance_engine import ComplianceDisposition
from .evidence_dependency_graph import EvidenceDependencyGraph
from .uncertainty_engine import fuse_confidence


class UnapprovedInputError(Exception):
    """Raised when the downstream fusion pipeline is handed anything other
    than an approved ComplianceDisposition. This is what "no item may enter
    the downstream fusion stub without an approved compliance decision"
    means in code, not just in a document."""


@dataclass
class DownstreamFusionOutcome:
    confidence_after: float
    explanation: str
    contributing_compliance_decision_ids: list


def _require_approved(disposition: ComplianceDisposition) -> None:
    if not isinstance(disposition, ComplianceDisposition):
        raise UnapprovedInputError(
            "downstream fusion pipeline only accepts ComplianceDisposition objects "
            "produced by ComplianceEngine.inspect() — raw sensor data is not a valid input"
        )
    if not disposition.approved:
        raise UnapprovedInputError(
            f"item {disposition.item_id} was not approved by the Fusion Compliance Engine "
            f"(disposition: {disposition.policy_decision.action.value}) and may not enter fusion"
        )


class DownstreamFusionPipeline:
    """Confidence fusion over already-cleared items only. Entity
    association/ranking itself happens upstream, in fusion_engine.py, over
    the raw candidate pool — it never reads the one sensitive field
    (raw_signal_signature) any policy rule blocks, so ranking on raw data
    carries no leakage risk (see docs/THREAT_MODEL.md). What this module
    guarantees is narrower and load-bearing: the *values that actually get
    combined into a confidence number* come only from FCE-approved,
    field-filtered items, never from a rejected or unfiltered one."""

    def __init__(self, dependency_graph: EvidenceDependencyGraph):
        self.dependency_graph = dependency_graph

    def fuse(
        self,
        camera_disposition: ComplianceDisposition,
        radar_disposition: ComplianceDisposition,
    ) -> DownstreamFusionOutcome:
        """Both items must already be registered in self.dependency_graph by
        the caller (fusion_engine.py registers every inspected item, camera
        and radar alike, as soon as its disposition is known) — this
        function only fuses, it does not itself decide independence."""
        _require_approved(camera_disposition)
        _require_approved(radar_disposition)

        camera_item = camera_disposition.filtered_item
        radar_item = radar_disposition.filtered_item

        confidence_after, explanation = fuse_confidence(
            camera_item.confidence_score,
            camera_item.id,
            radar_item.confidence_score,
            radar_item.id,
            self.dependency_graph,
        )
        return DownstreamFusionOutcome(
            confidence_after=confidence_after,
            explanation=explanation,
            contributing_compliance_decision_ids=[
                camera_disposition.compliance_decision_id,
                radar_disposition.compliance_decision_id,
            ],
        )
