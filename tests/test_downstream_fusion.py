import pytest

from fusion_compliance_loop.compliance_engine import ComplianceEngine
from fusion_compliance_loop.downstream_fusion import DownstreamFusionPipeline, UnapprovedInputError
from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain
from fusion_compliance_loop.evidence_dependency_graph import EvidenceDependencyGraph
from fusion_compliance_loop.policy_engine import PolicyEngine
from fusion_compliance_loop.provenance_recorder import ProvenanceRecorder
from fusion_compliance_loop.synthetic_sensor_generator import make_camera_detection, make_radar_pool


def _fixture():
    graph = EvidenceDependencyGraph()
    provenance = ProvenanceRecorder()
    engine = ComplianceEngine(policy_engine=PolicyEngine(), provenance=provenance, use_ai_risk=True)
    pipeline = DownstreamFusionPipeline(graph)
    return graph, provenance, engine, pipeline


def test_downstream_rejects_a_raw_data_item():
    _graph, _provenance, _engine, pipeline = _fixture()
    camera = make_camera_detection()
    with pytest.raises(UnapprovedInputError):
        pipeline.fuse(camera, camera)  # raw DataItem, not a ComplianceDisposition


def test_downstream_rejects_an_unapproved_disposition():
    _graph, _provenance, engine, pipeline = _fixture()
    camera = make_camera_detection()
    confidential = make_radar_pool(camera.timestamp, camera.location, seed=1)[0]
    confidential.classification_level = ClassificationLevel.CONFIDENTIAL
    confidential.release_permissions = [NetworkDomain.RESTRICTED_NET]

    camera_disp = engine.inspect(camera, NetworkDomain.OPEN)
    rejected_disp = engine.inspect(confidential, NetworkDomain.OPEN)
    assert not rejected_disp.approved

    with pytest.raises(UnapprovedInputError):
        pipeline.fuse(camera_disp, rejected_disp)


# 9. Forbidden fields never reach downstream fusion.
def test_forbidden_fields_never_reach_downstream_fusion():
    graph, provenance, engine, pipeline = _fixture()
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)  # pool[0] carries raw_signal_signature

    camera_disp = engine.inspect(camera, NetworkDomain.OPEN)
    graph.register(camera_disp.filtered_item)
    radar_disp = engine.inspect(pool[0], NetworkDomain.OPEN)
    graph.register(radar_disp.filtered_item)

    assert radar_disp.approved  # SEGREGATE, not REJECT
    outcome = pipeline.fuse(camera_disp, radar_disp)
    assert outcome.confidence_after > camera.confidence_score
    # The item the pipeline actually touched has the field stripped:
    assert radar_disp.filtered_item.raw_signal_signature is None


# 12. Every downstream output traces to original inputs.
def test_downstream_outcome_references_compliance_decision_ids():
    graph, provenance, engine, pipeline = _fixture()
    camera = make_camera_detection()
    pool = make_radar_pool(camera.timestamp, camera.location, seed=1)

    camera_disp = engine.inspect(camera, NetworkDomain.OPEN)
    graph.register(camera_disp.filtered_item)
    radar_disp = engine.inspect(pool[1], NetworkDomain.OPEN)  # PUBLIC candidate, PERMIT
    graph.register(radar_disp.filtered_item)

    outcome = pipeline.fuse(camera_disp, radar_disp)
    assert camera_disp.compliance_decision_id in outcome.contributing_compliance_decision_ids
    assert radar_disp.compliance_decision_id in outcome.contributing_compliance_decision_ids
    # The Fusion Compliance Engine recorded both original raw items as
    # provenance nodes as soon as each was inspected — independent of
    # whether downstream fusion ever runs.
    assert camera.id in provenance.graph
    assert pool[1].id in provenance.graph
