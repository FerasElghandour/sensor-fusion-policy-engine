from fusion_compliance_loop.fusion_engine import FusionEngine
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


def test_conclusion_traces_back_to_original_inputs():
    camera = make_camera_detection()
    engine = FusionEngine()
    result = engine.run(camera, lambda: make_radar_pool(camera.timestamp, camera.location, seed=1))

    trace = engine.provenance.trace_to_inputs(result.conclusion_id)
    assert camera.id in trace
    for contributing_id in result.contributing_data_ids:
        assert contributing_id in trace or contributing_id == result.conclusion_id
