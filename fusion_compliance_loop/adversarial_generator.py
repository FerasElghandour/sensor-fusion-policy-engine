"""Configurable adversarial mission generator.

Each mission is a synthetic camera+radar fusion problem with a known ground
truth (correct match, fields that must be blocked/may be fused, expected
provenance chain). generate_missions() combines 20 adversarial conditions
(see ADVERSARIAL_CONDITIONS) so the benchmark can measure how well each
approach in benchmarks/approaches.py holds up under noisy, delayed,
conflicting, incomplete, and outright adversarial input — never against real
sensors or operational data, only this synthetic generator.
"""

import base64
import random
from dataclasses import dataclass, field
from datetime import timedelta

from .enums import ClassificationLevel, NetworkDomain
from .models import CameraDetection, Location, RadarDetection
from .synthetic_sensor_generator import make_camera_detection, make_radar_pool

ADVERSARIAL_CONDITIONS = [
    "delayed_timestamps",
    "clock_drift",
    "missing_timestamps",
    "missing_classifications",
    "incorrect_classifications",
    "conflicting_locations",
    "multiple_possible_matches",
    "duplicate_evidence",
    "evidence_derived_from_same_source",
    "sensor_noise",
    "sensor_failure",
    "communication_delay",
    "corrupted_metadata",
    "missing_release_permission",
    "unauthorized_cross_domain_request",
    "policy_conflict",
    "rapid_policy_change",
    "repeated_evidence_seeking_loop",
    "insert_restricted_field",
    "disguise_restricted_field",
    "missing_metadata_markings",
    "camera_side_forbidden_domain",
    "protected_b_cross_domain",
]


@dataclass
class Mission:
    mission_id: str
    camera: CameraDetection
    radar_pool: list[RadarDetection]
    network_domain: NetworkDomain
    max_sensor_requests: int
    tags: list[str]
    ground_truth: dict


@dataclass
class _MissionContext:
    rng: random.Random
    camera: CameraDetection
    radar_pool: list[RadarDetection]
    network_domain: NetworkDomain
    max_sensor_requests: int
    ground_truth: dict = field(default_factory=dict)


def _new_ground_truth(camera: CameraDetection, true_radar: RadarDetection) -> dict:
    must_block = ["raw_signal_signature"] if true_radar.raw_signal_signature is not None else []
    return {
        "correct_match_radar_id": true_radar.id,
        "fields_that_must_be_blocked": must_block,
        "fields_that_may_be_fused": ["speed_mps", "distance_m", "direction_deg", "confidence_score"],
        "expected_provenance_chain": [camera.id, true_radar.id],
        "requires_review_or_block": true_radar.classification_level != ClassificationLevel.PUBLIC,
        "is_dependent_evidence": False,
        "expects_camera_rejected": False,
        "is_protected_b": False,
    }


def _true_radar(ctx: _MissionContext) -> RadarDetection:
    true_id = ctx.ground_truth["correct_match_radar_id"]
    return next(r for r in ctx.radar_pool if r.id == true_id)


# --- individual mutations, one per adversarial condition ------------------


def _mut_delayed_timestamps(ctx: _MissionContext) -> None:
    delay = ctx.rng.uniform(10, 45)
    for r in ctx.radar_pool:
        if r.timestamp is not None:
            r.timestamp = r.timestamp + timedelta(seconds=delay)


def _mut_clock_drift(ctx: _MissionContext) -> None:
    drift = ctx.rng.choice([-1, 1]) * ctx.rng.uniform(20, 90)
    for r in ctx.radar_pool:
        if r.timestamp is not None:
            r.timestamp = r.timestamp + timedelta(seconds=drift)


def _mut_missing_timestamps(ctx: _MissionContext) -> None:
    if ctx.rng.random() < 0.5:
        ctx.camera.timestamp = None
    else:
        _true_radar(ctx).timestamp = None


def _mut_missing_classifications(ctx: _MissionContext) -> None:
    # Radar item is never explicitly classified — defaults to PUBLIC even
    # though it still carries a field that should be RESTRICTED.
    _true_radar(ctx).classification_level = ClassificationLevel.PUBLIC


def _mut_incorrect_classifications(ctx: _MissionContext) -> None:
    # Deliberately mislabeled one level below its true sensitivity.
    _true_radar(ctx).classification_level = ClassificationLevel.SENSITIVE


def _mut_conflicting_locations(ctx: _MissionContext) -> None:
    offset = ctx.rng.uniform(300, 900)
    for r in ctx.radar_pool:
        if r.location is not None:
            r.location = Location(x=r.location.x + offset, y=r.location.y + offset)


def _mut_multiple_possible_matches(ctx: _MissionContext) -> None:
    for r in ctx.radar_pool:
        r.confidence_score = round(ctx.rng.uniform(0.55, 0.65), 2)
        r.location = Location(
            x=ctx.camera.location.x + ctx.rng.uniform(0.5, 1.5),
            y=ctx.camera.location.y + ctx.rng.uniform(0.5, 1.5),
        )
        if ctx.camera.direction_deg is not None:
            r.direction_deg = ctx.camera.direction_deg + ctx.rng.uniform(-8, 8)


def _mut_duplicate_evidence(ctx: _MissionContext) -> None:
    true_item = _true_radar(ctx)
    duplicate = true_item.model_copy(deep=True, update={"id": true_item.id + "-dup"})
    duplicate.parent_data_ids = [true_item.id]
    ctx.radar_pool.append(duplicate)
    ctx.ground_truth["is_dependent_evidence"] = True


def _mut_evidence_derived_from_same_source(ctx: _MissionContext) -> None:
    _true_radar(ctx).parent_data_ids = [ctx.camera.id]
    ctx.ground_truth["is_dependent_evidence"] = True


def _mut_sensor_noise(ctx: _MissionContext) -> None:
    for r in ctx.radar_pool:
        if r.speed_mps is not None:
            r.speed_mps = max(0.0, r.speed_mps + ctx.rng.gauss(0, 3))
        if r.distance_m is not None:
            r.distance_m = max(0.0, r.distance_m + ctx.rng.gauss(0, 2))
        r.confidence_score = min(0.99, max(0.05, r.confidence_score + ctx.rng.gauss(0, 0.08)))


def _mut_sensor_failure(ctx: _MissionContext) -> None:
    ctx.radar_pool.clear()
    ctx.ground_truth.update(
        correct_match_radar_id=None,
        fields_that_must_be_blocked=[],
        fields_that_may_be_fused=[],
        expected_provenance_chain=[ctx.camera.id],
    )


def _mut_communication_delay(ctx: _MissionContext) -> None:
    # The camera feed itself lags — distinct from radar-side delay/drift.
    if ctx.camera.timestamp is not None:
        ctx.camera.timestamp = ctx.camera.timestamp + timedelta(seconds=ctx.rng.uniform(5, 20))


def _mut_corrupted_metadata(ctx: _MissionContext) -> None:
    _true_radar(ctx).distance_m = ctx.rng.choice([-999.0, 999999.0])


def _mut_missing_release_permission(ctx: _MissionContext) -> None:
    target = _true_radar(ctx)
    target.classification_level = ClassificationLevel.SENSITIVE
    target.release_permissions = []
    target.raw_signal_signature = None  # isolate from the misclassification case


def _mut_unauthorized_cross_domain_request(ctx: _MissionContext) -> None:
    target = _true_radar(ctx)
    target.release_permissions = [NetworkDomain.OPEN]
    ctx.network_domain = NetworkDomain.RESTRICTED_NET


def _mut_policy_conflict(ctx: _MissionContext) -> None:
    # Satisfies more than one rule's conditions at once (RESTRICTED_CROSS_DOMAIN
    # and MISSING_RELEASE_PERMISSION both match) — priority order must resolve
    # this the same way every time.
    target = _true_radar(ctx)
    target.classification_level = ClassificationLevel.RESTRICTED
    target.release_permissions = []


def _mut_rapid_policy_change(ctx: _MissionContext) -> None:
    pass  # tag only — benchmarks/run_all.py reloads the live policy for these missions


def _mut_repeated_evidence_seeking_loop(ctx: _MissionContext) -> None:
    ctx.max_sensor_requests = 1


def _mut_insert_restricted_field(ctx: _MissionContext) -> None:
    # Looks fully authorized (PUBLIC, released everywhere) but still smuggles
    # a restricted-sensitivity field in the payload.
    target = _true_radar(ctx)
    target.classification_level = ClassificationLevel.PUBLIC
    target.release_permissions = [NetworkDomain.OPEN, NetworkDomain.PARTNER, NetworkDomain.INTERNAL, NetworkDomain.RESTRICTED_NET]
    target.raw_signal_signature = "sig-adversarial-insert"


def _mut_disguise_restricted_field(ctx: _MissionContext) -> None:
    # Same idea, but the sensitive value is also obfuscated (base64) — proves
    # detection is field-name-based, not content-based (see THREAT_MODEL.md).
    target = _true_radar(ctx)
    target.classification_level = ClassificationLevel.PUBLIC
    target.release_permissions = [NetworkDomain.OPEN]
    raw = target.raw_signal_signature or "sig-hidden"
    target.raw_signal_signature = base64.b64encode(raw.encode()).decode()


def _mut_missing_metadata_markings(ctx: _MissionContext) -> None:
    # No classification/domain/release-authority marking on file at all —
    # distinct from a wrong VALUE (misclassification): here the metadata
    # block itself is absent. Only the AI compliance-risk detector reads
    # these three flags; deterministic rules don't, so this condition
    # specifically measures whether the AI-driven escalation path catches
    # what field-value-based rules alone cannot.
    target = _true_radar(ctx)
    target.classification_marking_present = False
    target.domain_of_origin_marking_present = False
    target.release_authority_marking_present = False


def _mut_camera_side_forbidden_domain(ctx: _MissionContext) -> None:
    # Mirrors unauthorized_cross_domain_request but on the CAMERA modality —
    # proves compliance enforcement isn't radar-only.
    ctx.camera.classification_level = ClassificationLevel.CONFIDENTIAL
    ctx.camera.release_permissions = [NetworkDomain.RESTRICTED_NET]
    ctx.ground_truth["expects_camera_rejected"] = True


def _mut_protected_b_cross_domain(ctx: _MissionContext) -> None:
    # Synthetic Protected B label crossing from CANADA_PROTECTED into
    # COALITION_UNCLASSIFIED without release authority — simulated policy
    # enforcement only, not real Protected B accreditation.
    target = _true_radar(ctx)
    target.classification_level = ClassificationLevel.PROTECTED_B
    target.network_domain = NetworkDomain.CANADA_PROTECTED
    target.release_permissions = [NetworkDomain.CANADA_PROTECTED]
    ctx.network_domain = NetworkDomain.COALITION_UNCLASSIFIED
    ctx.ground_truth["is_protected_b"] = True


MUTATIONS = {
    "delayed_timestamps": _mut_delayed_timestamps,
    "clock_drift": _mut_clock_drift,
    "missing_timestamps": _mut_missing_timestamps,
    "missing_classifications": _mut_missing_classifications,
    "incorrect_classifications": _mut_incorrect_classifications,
    "conflicting_locations": _mut_conflicting_locations,
    "multiple_possible_matches": _mut_multiple_possible_matches,
    "duplicate_evidence": _mut_duplicate_evidence,
    "evidence_derived_from_same_source": _mut_evidence_derived_from_same_source,
    "sensor_noise": _mut_sensor_noise,
    "sensor_failure": _mut_sensor_failure,
    "communication_delay": _mut_communication_delay,
    "corrupted_metadata": _mut_corrupted_metadata,
    "missing_release_permission": _mut_missing_release_permission,
    "unauthorized_cross_domain_request": _mut_unauthorized_cross_domain_request,
    "policy_conflict": _mut_policy_conflict,
    "rapid_policy_change": _mut_rapid_policy_change,
    "repeated_evidence_seeking_loop": _mut_repeated_evidence_seeking_loop,
    "insert_restricted_field": _mut_insert_restricted_field,
    "disguise_restricted_field": _mut_disguise_restricted_field,
    "missing_metadata_markings": _mut_missing_metadata_markings,
    "camera_side_forbidden_domain": _mut_camera_side_forbidden_domain,
    "protected_b_cross_domain": _mut_protected_b_cross_domain,
}

assert set(MUTATIONS) == set(ADVERSARIAL_CONDITIONS)


def _finalize_ground_truth(ctx: _MissionContext) -> None:
    """Recompute the blocking/review ground truth from the FINAL state of the
    true-match item, after every chosen mutation has run. Individual
    mutations only change item fields (classification, permissions, the
    payload) — they never set this ground truth themselves, so combining
    several conditions on one mission can't leave a stale, clobbered answer.

    The rule is deliberately simple and independent of any declared label:
    if the sensitive field is still populated, it must be blocked — no
    matter what classification/permissions an attacker attached to disguise
    it. That mirrors exactly what an adversarial test is supposed to prove."""
    # Mutations can change the destination after marking the camera as
    # confidential. Derive this oracle from the final envelope, even when
    # sensor_failure removed the radar pool. A condition tag is not truth.
    ctx.ground_truth["expects_camera_rejected"] = (
        ctx.camera.classification_level == ClassificationLevel.CONFIDENTIAL
        and ctx.network_domain not in ctx.camera.release_permissions
    )
    true_id = ctx.ground_truth.get("correct_match_radar_id")
    if true_id is None:
        return  # sensor_failure already recorded the "no match possible" truth
    true_item = next((r for r in ctx.radar_pool if r.id == true_id), None)
    if true_item is None:
        return

    must_block = ["raw_signal_signature"] if true_item.raw_signal_signature is not None else []
    ctx.ground_truth["fields_that_must_be_blocked"] = must_block
    ctx.ground_truth["requires_review_or_block"] = (
        bool(must_block)
        or true_item.classification_level != ClassificationLevel.PUBLIC
        or not true_item.release_permissions
        or ctx.network_domain not in true_item.release_permissions
    )


def generate_missions(n: int = 1000, seed: int = 7) -> list[Mission]:
    """Generate n synthetic fusion missions. The first 2*len(ADVERSARIAL_CONDITIONS)
    missions each apply exactly one condition in isolation (guaranteed
    coverage); the remainder combine 0-3 conditions at random so later
    missions exercise real combinations, not just single-factor cases."""
    rng = random.Random(seed)
    tag_names = list(MUTATIONS.keys())

    forced = tag_names * 2
    rng.shuffle(forced)

    missions: list[Mission] = []
    for i in range(n):
        mission_seed = rng.randint(0, 2**31 - 1)
        mission_rng = random.Random(mission_seed)

        camera = make_camera_detection(confidence=round(mission_rng.uniform(0.45, 0.7), 2))
        radar_pool = make_radar_pool(camera.timestamp, camera.location, seed=mission_seed)
        ground_truth = _new_ground_truth(camera, radar_pool[0])

        ctx = _MissionContext(
            rng=mission_rng,
            camera=camera,
            radar_pool=radar_pool,
            network_domain=NetworkDomain.OPEN,
            max_sensor_requests=3,
            ground_truth=ground_truth,
        )

        if i < len(forced):
            chosen_tags = [forced[i]]
        else:
            k = mission_rng.choice([0, 1, 1, 2, 2, 3])
            chosen_tags = mission_rng.sample(tag_names, k) if k else []

        # sensor_failure clears the radar pool entirely, so it must run last —
        # any other mutation still expects a radar candidate to exist.
        ordered_tags = sorted(chosen_tags, key=lambda t: t == "sensor_failure")
        for tag in ordered_tags:
            MUTATIONS[tag](ctx)
        _finalize_ground_truth(ctx)

        missions.append(
            Mission(
                mission_id=f"mission-{i:05d}",
                camera=ctx.camera,
                radar_pool=ctx.radar_pool,
                network_domain=ctx.network_domain,
                max_sensor_requests=ctx.max_sensor_requests,
                tags=sorted(set(chosen_tags)),
                ground_truth=ctx.ground_truth,
            )
        )
    return missions
