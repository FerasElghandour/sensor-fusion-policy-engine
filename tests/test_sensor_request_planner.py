from fusion_compliance_loop.active_sensor_request_planner import SensorRequestPlanner


def test_missing_fields_detected_on_incomplete_item():
    from fusion_compliance_loop.models import CameraDetection

    item = CameraDetection(confidence_score=0.5)
    planner = SensorRequestPlanner()
    # CameraDetection never carries speed/distance, so both always show missing
    # until radar evidence resolves them — this is the "camera reports a
    # vehicle but lacks speed/distance" case from the first scenario.
    assert planner.missing_fields(item) == ["speed_mps", "distance_m"]


def test_request_loop_stops_at_configured_limit():
    planner = SensorRequestPlanner(max_requests=2)
    missing = ["speed_mps", "distance_m"]
    outcomes = [planner.request(missing) for _ in range(5)]
    assert planner.requests_made == 2
    assert outcomes[2:] == [None, None, None]
    assert any("LIMIT_REACHED" in line for line in planner.request_log)
