"""Ten automated scenarios exercising normal matching, degraded inputs,
dependent evidence, and every compliance policy action. Each fusion scenario
returns (name, engine, camera, result); the repeated-loop scenario returns
(name, planner, None, outcomes) since it doesn't need a camera/radar pair.
"""

from datetime import datetime, timedelta, timezone

from .active_sensor_request_planner import SensorRequestPlanner
from .enums import ClassificationLevel, NetworkDomain
from .fusion_engine import FusionEngine
from .models import Location
from .synthetic_sensor_generator import make_camera_detection, make_radar_pool


def scenario_normal_matching(policy_engine=None):
    camera = make_camera_detection()
    engine = FusionEngine(policy_engine=policy_engine)
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))
    return "normal_matching", engine, camera, result


def scenario_delayed_sensor_data(policy_engine=None):
    camera = make_camera_detection()
    engine = FusionEngine(policy_engine=policy_engine)

    def late_radar_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=2)
        for r in pool:
            r.timestamp = r.timestamp + timedelta(seconds=30)  # outside the alignment window
        return pool

    result = engine.run(camera, late_radar_pool)
    return "delayed_sensor_data", engine, camera, result


def scenario_missing_timestamp(policy_engine=None):
    camera = make_camera_detection()
    camera.timestamp = None
    engine = FusionEngine(policy_engine=policy_engine)
    result = engine.run(camera, lambda: make_radar_pool(datetime.now(timezone.utc), camera.location, seed=3))
    return "missing_timestamp", engine, camera, result


def scenario_conflicting_locations(policy_engine=None):
    camera = make_camera_detection()
    engine = FusionEngine(policy_engine=policy_engine)

    def far_radar_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=4)
        for r in pool:
            r.location = Location(x=r.location.x + 500, y=r.location.y + 500)
        return pool

    result = engine.run(camera, far_radar_pool)
    return "conflicting_locations", engine, camera, result


def scenario_multiple_possible_matches(policy_engine=None):
    camera = make_camera_detection()
    engine = FusionEngine(policy_engine=policy_engine)

    def close_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=5)
        for r in pool:
            r.confidence_score = 0.5
            r.location = Location(x=camera.location.x + 1.0, y=camera.location.y + 1.0)
        return pool

    result = engine.run(camera, close_pool)
    return "multiple_possible_matches", engine, camera, result


def scenario_dependent_evidence(policy_engine=None):
    camera = make_camera_detection()
    engine = FusionEngine(policy_engine=policy_engine)

    def derived_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=6)
        # This radar return was actually derived from the same camera frame,
        # not an independent observation — the dependency graph must catch it.
        pool[0].parent_data_ids = [camera.id]
        return pool

    result = engine.run(camera, derived_pool)
    return "dependent_evidence", engine, camera, result


def scenario_incorrect_classification_markings(policy_engine=None):
    camera = make_camera_detection()
    engine = FusionEngine(policy_engine=policy_engine)

    def mislabeled_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=7)
        # Carries a raw signal field but is mismarked as PUBLIC.
        pool[0].classification_level = ClassificationLevel.PUBLIC
        pool[0].release_permissions = [NetworkDomain.OPEN]
        pool[0].raw_signal_signature = "sig-9999"
        return pool

    result = engine.run(camera, mislabeled_pool)
    return "incorrect_classification_markings", engine, camera, result


def scenario_forbidden_cross_domain_fusion(policy_engine=None):
    camera = make_camera_detection()
    engine = FusionEngine(policy_engine=policy_engine, network_domain=NetworkDomain.OPEN)

    def confidential_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=8)
        pool[0].classification_level = ClassificationLevel.CONFIDENTIAL
        pool[0].release_permissions = [NetworkDomain.RESTRICTED_NET]
        return pool

    result = engine.run(camera, confidential_pool)
    return "forbidden_cross_domain_fusion", engine, camera, result


def scenario_missing_release_permissions(policy_engine=None):
    camera = make_camera_detection()
    engine = FusionEngine(policy_engine=policy_engine)

    def unreleased_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=9)
        pool[0].classification_level = ClassificationLevel.SENSITIVE
        pool[0].release_permissions = []
        # Clear the field that made this candidate RESTRICTED by default —
        # this scenario isolates "no release permissions on file" from the
        # separate "field sensitivity doesn't match its declared level" case.
        pool[0].raw_signal_signature = None
        return pool

    result = engine.run(camera, unreleased_pool)
    return "missing_release_permissions", engine, camera, result


def scenario_repeated_evidence_seeking_loop(policy_engine=None):
    planner = SensorRequestPlanner(max_requests=2)
    missing = ["speed_mps", "distance_m"]
    outcomes = [planner.request(missing) for _ in range(5)]
    return "repeated_evidence_seeking_loop", planner, None, outcomes


def scenario_protected_b_cross_domain(policy_engine=None):
    """v0.3: a synthetic Protected B radar return, released for
    CANADA_PROTECTED, evaluated against COALITION_UNCLASSIFIED without
    release authority for that domain — segregated, not permitted in full.
    Simulated policy enforcement only; not real Protected B accreditation."""
    camera = make_camera_detection()
    engine = FusionEngine(policy_engine=policy_engine, network_domain=NetworkDomain.COALITION_UNCLASSIFIED)

    def protected_b_pool():
        pool = make_radar_pool(camera.timestamp, camera.location, seed=10)
        pool[0].classification_level = ClassificationLevel.PROTECTED_B
        pool[0].network_domain = NetworkDomain.CANADA_PROTECTED
        pool[0].release_permissions = [NetworkDomain.CANADA_PROTECTED]
        return pool

    result = engine.run(camera, protected_b_pool)
    return "protected_b_cross_domain", engine, camera, result


def scenario_camera_side_blocked_independently(policy_engine=None):
    """v0.3: the CAMERA modality itself carries CONFIDENTIAL data not
    released for the operating domain — the Fusion Compliance Engine blocks
    it before radar is ever requested, proving camera-side enforcement is
    real and independent of whatever the radar pool contains."""
    camera = make_camera_detection(
        classification_level=ClassificationLevel.CONFIDENTIAL,
        release_permissions=[NetworkDomain.RESTRICTED_NET],
    )
    engine = FusionEngine(policy_engine=policy_engine, network_domain=NetworkDomain.OPEN)
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=11))
    return "camera_side_blocked_independently", engine, camera, result


SCENARIOS = [
    scenario_normal_matching,
    scenario_delayed_sensor_data,
    scenario_missing_timestamp,
    scenario_conflicting_locations,
    scenario_multiple_possible_matches,
    scenario_dependent_evidence,
    scenario_incorrect_classification_markings,
    scenario_forbidden_cross_domain_fusion,
    scenario_missing_release_permissions,
    scenario_repeated_evidence_seeking_loop,
    scenario_protected_b_cross_domain,
    scenario_camera_side_blocked_independently,
]
