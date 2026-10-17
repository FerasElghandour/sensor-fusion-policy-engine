"""Regression for seven stale camera labels found by the multi-seed audit."""
import random
from types import SimpleNamespace
import pytest
from fusion_compliance_loop.adversarial_generator import (
    _MissionContext, _finalize_ground_truth, _mut_camera_side_forbidden_domain,
    _mut_unauthorized_cross_domain_request, generate_missions,
)
from fusion_compliance_loop.enums import NetworkDomain
from fusion_compliance_loop.policy_engine import PolicyEngine
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


@pytest.mark.parametrize("reverse", [False, True])
def test_combined_conditions_use_final_destination_not_stale_tag(reverse):
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)
    ctx = _MissionContext(rng=random.Random(1), camera=camera, radar_pool=pool,
                         network_domain=NetworkDomain.OPEN, max_sensor_requests=3,
                         ground_truth={"correct_match_radar_id": pool[0].id})
    mutations = [_mut_camera_side_forbidden_domain, _mut_unauthorized_cross_domain_request]
    for mutation in mutations[:: -1 if reverse else 1]:
        mutation(ctx)
    _finalize_ground_truth(ctx)
    assert ctx.network_domain == NetworkDomain.RESTRICTED_NET
    assert ctx.ground_truth["expects_camera_rejected"] is False
    assert PolicyEngine().evaluate(camera, ctx.network_domain).action.value == "PERMIT"


def test_camera_oracle_is_recomputed_even_when_no_radar_exists():
    camera = make_camera_detection()
    ctx = _MissionContext(rng=random.Random(1), camera=camera, radar_pool=[],
                         network_domain=NetworkDomain.OPEN, max_sensor_requests=3,
                         ground_truth={"correct_match_radar_id": None})
    _mut_camera_side_forbidden_domain(ctx)
    _finalize_ground_truth(ctx)
    assert ctx.ground_truth["expects_camera_rejected"] is True
    assert PolicyEngine().evaluate(camera, ctx.network_domain).action.value == "REJECT"


@pytest.mark.parametrize("seed,indices", [(19, [791]), (42, [277, 462, 566, 576, 838, 870])])
def test_discovered_cases_are_legitimate_releases_not_policy_bypasses(seed, indices):
    missions = generate_missions(n=1000, seed=seed)
    for index in indices:
        mission = missions[index]
        assert "camera_side_forbidden_domain" in mission.tags
        assert "unauthorized_cross_domain_request" in mission.tags
        assert mission.network_domain in mission.camera.release_permissions
        assert mission.ground_truth["expects_camera_rejected"] is False
