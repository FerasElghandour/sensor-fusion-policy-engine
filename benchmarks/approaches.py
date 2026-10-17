"""Three approaches run over the same adversarial mission set, per
docs/BENCHMARK_METHOD.md:

A. Static threshold matching, no compliance engine at all.
B. The existing deterministic association engine + the compliance engine.
C. model-based association (ai_entity_association) + the same compliance engine.

Approach A exists purely as a naive baseline — it demonstrates what leaks
when nothing enforces policy. B and C always route through the same
policy_engine.apply(), so the AI in C can only change *which* candidate gets
proposed, never whether policy is enforced on it.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from fusion_compliance_loop.adversarial_generator import Mission
from fusion_compliance_loop.ai_entity_association import get_default_model
from fusion_compliance_loop.fusion_engine import FusionEngine
from fusion_compliance_loop.policy_engine import DEFAULT_POLICY_PATH, PolicyEngine

ALT_POLICY_PATH = DEFAULT_POLICY_PATH.parent / "alt_policy_v1_1.yaml"

TRACKED_FIELDS = ("speed_mps", "distance_m", "direction_deg", "confidence_score", "raw_signal_signature")


@dataclass
class MissionOutcome:
    mission_id: str
    approach: str
    predicted_match_radar_id: Optional[str]
    fused_fields_present: set
    blocked_fields: list
    policy_action: Optional[str]
    policy_id: Optional[str] = None
    policy_version: Optional[str] = None
    latency_s: float = 0.0
    provenance_chain: list = field(default_factory=list)
    explanation: str = ""
    evidence_loop_terminated: bool = True
    confidence_before: Optional[float] = None
    confidence_after: Optional[float] = None
    top_candidate_score: Optional[float] = None
    tags: list = field(default_factory=list)
    error: Optional[str] = None
    # v0.3 (compliance-risk audit): camera-side disposition and the AI
    # compliance-risk signal for the winning radar candidate, so benchmark
    # metrics can measure both modalities and the AI's contribution
    # separately from entity-association performance.
    camera_approved: Optional[bool] = None
    camera_policy_action: Optional[str] = None
    ai_risk_probability: Optional[float] = None
    ai_risk_categories: list = field(default_factory=list)


def _static_threshold_match(camera, radar_pool, time_window: float = 2.0, distance_window: float = 20.0):
    """The naive baseline: first radar reading within a fixed time/distance
    window, no weighting, no ranking, no policy check of any kind."""
    for r in radar_pool:
        if camera.timestamp is None or r.timestamp is None or camera.location is None or r.location is None:
            continue
        time_diff = abs((camera.timestamp - r.timestamp).total_seconds())
        dist = ((camera.location.x - r.location.x) ** 2 + (camera.location.y - r.location.y) ** 2) ** 0.5
        if time_diff <= time_window and dist <= distance_window:
            return r
    return None


def run_approach_a(mission: Mission) -> MissionOutcome:
    t0 = time.perf_counter()
    match = _static_threshold_match(mission.camera, mission.radar_pool)
    fused = set()
    if match is not None:
        for f in TRACKED_FIELDS:
            if getattr(match, f, None) is not None:
                fused.add(f)
    latency = time.perf_counter() - t0
    return MissionOutcome(
        mission_id=mission.mission_id,
        approach="A_static_threshold_no_compliance",
        predicted_match_radar_id=match.id if match else None,
        fused_fields_present=fused,
        blocked_fields=[],
        policy_action="PERMIT" if match else None,
        latency_s=latency,
        provenance_chain=[],  # no provenance recorder in this baseline
        explanation="",  # no explanation generated
        evidence_loop_terminated=True,  # no request loop exists to get stuck
        confidence_before=mission.camera.confidence_score,
        confidence_after=None,  # this baseline does no confidence reasoning at all
        tags=list(mission.tags),
    )


def run_approach_a_batch(missions: list[Mission]) -> list[MissionOutcome]:
    return [run_approach_a(m) for m in missions]


def _run_fusion_based(
    mission: Mission,
    approach_name: str,
    use_ai: bool,
    policy_engine: PolicyEngine,
    ai_model=None,
) -> MissionOutcome:
    t0 = time.perf_counter()
    pool = list(mission.radar_pool)
    engine = FusionEngine(
        network_domain=mission.network_domain,
        max_sensor_requests=mission.max_sensor_requests,
        policy_engine=policy_engine,
    )
    try:
        result = engine.run(mission.camera, lambda: pool, use_ai_association=use_ai, ai_model=ai_model)
    except Exception as exc:  # noqa: BLE001 - a mission that crashes IS a benchmark result
        latency = time.perf_counter() - t0
        return MissionOutcome(
            mission_id=mission.mission_id,
            approach=approach_name,
            predicted_match_radar_id=None,
            fused_fields_present=set(),
            blocked_fields=[],
            policy_action=None,
            latency_s=latency,
            provenance_chain=[],
            explanation="",
            evidence_loop_terminated=False,
            error=repr(exc),
        )
    finally:
        engine.provenance.conn.close()
    latency = time.perf_counter() - t0

    predicted_match_radar_id = result.candidates_considered[0].radar_id if result.candidates_considered else None
    matched_radar_id = result.contributing_data_ids[1] if len(result.contributing_data_ids) > 1 else None

    fused_fields = set()
    if matched_radar_id:
        matched = next((r for r in pool if r.id == matched_radar_id), None)
        if matched:
            for f in TRACKED_FIELDS:
                val = getattr(matched, f, None)
                if val is not None and f not in result.blocked_fields:
                    fused_fields.add(f)

    policy_action = result.applied_policy_rules[-1].split(":")[-1] if result.applied_policy_rules else None
    policy_id = policy_version = None
    probe_id = matched_radar_id or predicted_match_radar_id
    winning_disposition = next(
        (d for d in result.radar_dispositions if d["item_id"] == predicted_match_radar_id), None
    )
    if winning_disposition is not None:
        policy_id, policy_version = winning_disposition["policy_id"], winning_disposition["policy_version"]
    elif probe_id:
        probe_item = next((r for r in pool if r.id == probe_id), None)
        if probe_item is not None:
            # Fallback pure read for the (rare) case ranking picked a
            # candidate the compliance engine never inspected.
            decision = policy_engine.evaluate(probe_item, mission.network_domain)
            policy_id, policy_version = decision.policy_id, decision.policy_version
    elif result.camera_policy_id:
        # No radar candidate was ever inspected (e.g. the camera itself was
        # rejected before any radar request went out) — attribute the
        # decision to the camera's own policy_id/version rather than
        # leaving it unset.
        policy_id, policy_version = result.camera_policy_id, result.camera_policy_version

    return MissionOutcome(
        mission_id=mission.mission_id,
        approach=approach_name,
        predicted_match_radar_id=predicted_match_radar_id,
        fused_fields_present=fused_fields,
        blocked_fields=list(result.blocked_fields),
        policy_action=policy_action,
        policy_id=policy_id,
        policy_version=policy_version,
        latency_s=latency,
        provenance_chain=engine.provenance.trace_to_inputs(result.conclusion_id),
        explanation=result.explanation,
        evidence_loop_terminated=engine.planner.requests_made <= engine.planner.max_requests,
        confidence_before=result.confidence_before,
        confidence_after=result.confidence_after,
        top_candidate_score=result.candidates_considered[0].association_score if result.candidates_considered else None,
        tags=list(mission.tags),
        camera_approved=result.camera_approved,
        camera_policy_action=result.camera_policy_rule.split(":")[-1] if result.camera_policy_rule else None,
        ai_risk_probability=winning_disposition["ai_risk_probability"] if winning_disposition else None,
        ai_risk_categories=list(winning_disposition["ai_risk_categories"]) if winning_disposition else [],
    )


def _run_batch_with_policy_churn(missions: list[Mission], approach_name: str, use_ai: bool, ai_model=None) -> list[MissionOutcome]:
    """Missions tagged rapid_policy_change reload the SAME shared PolicyEngine
    to the alternate policy just for that mission, then reload back — this
    exercises many real reload cycles across the batch (not one at startup),
    proving hot-reload works repeatedly under live traffic."""
    policy_engine = PolicyEngine()
    outcomes = []
    for mission in missions:
        if "rapid_policy_change" in mission.tags:
            policy_engine.reload_from_path(ALT_POLICY_PATH)
            outcomes.append(_run_fusion_based(mission, approach_name, use_ai, policy_engine, ai_model))
            policy_engine.reload_from_path(DEFAULT_POLICY_PATH)
        else:
            outcomes.append(_run_fusion_based(mission, approach_name, use_ai, policy_engine, ai_model))
    return outcomes


def run_approach_b_batch(missions: list[Mission]) -> list[MissionOutcome]:
    return _run_batch_with_policy_churn(missions, "B_deterministic_plus_compliance", use_ai=False)


def run_approach_c_batch(missions: list[Mission]) -> list[MissionOutcome]:
    ai_model = get_default_model()
    return _run_batch_with_policy_churn(missions, "C_ai_assisted_plus_compliance", use_ai=True, ai_model=ai_model)
