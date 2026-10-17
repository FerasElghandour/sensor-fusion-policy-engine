from fusion_compliance_loop.entity_association_engine import rank_candidates
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


def test_rank_candidates_orders_by_association_score():
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)
    ranked = rank_candidates(camera, pool)
    scores = [c.association_score for c in ranked]
    assert scores == sorted(scores, reverse=True)


def test_best_candidate_is_the_close_well_aligned_one():
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)
    ranked = rank_candidates(camera, pool)
    best = ranked[0]
    # pool[0] is the close, well-timed, well-aligned synthetic match.
    assert best.radar_id == pool[0].id


def test_multiple_close_candidates_all_returned():
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)
    ranked = rank_candidates(camera, pool)
    assert len(ranked) == len(pool)
