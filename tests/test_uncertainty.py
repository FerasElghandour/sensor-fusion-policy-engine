from fusion_compliance_loop.evidence_dependency_graph import EvidenceDependencyGraph
from fusion_compliance_loop.models import CameraDetection, RadarDetection
from fusion_compliance_loop.uncertainty_engine import fuse_confidence


def test_independent_evidence_compounds_upward():
    graph = EvidenceDependencyGraph()
    a = CameraDetection(confidence_score=0.55)
    b = RadarDetection(confidence_score=0.6)
    graph.register(a)
    graph.register(b)
    fused, _ = fuse_confidence(a.confidence_score, a.id, b.confidence_score, b.id, graph)
    assert fused > max(a.confidence_score, b.confidence_score)


def test_dependent_evidence_does_not_increase_confidence():
    graph = EvidenceDependencyGraph()
    a = CameraDetection(confidence_score=0.55)
    graph.register(a)
    b = RadarDetection(confidence_score=0.6, parent_data_ids=[a.id])
    graph.register(b)
    fused, explanation = fuse_confidence(a.confidence_score, a.id, b.confidence_score, b.id, graph)
    assert fused == max(a.confidence_score, b.confidence_score)
    assert "NOT" in explanation


def test_fused_confidence_never_exceeds_cap():
    graph = EvidenceDependencyGraph()
    a = CameraDetection(confidence_score=0.95)
    b = RadarDetection(confidence_score=0.97)
    graph.register(a)
    graph.register(b)
    fused, _ = fuse_confidence(a.confidence_score, a.id, b.confidence_score, b.id, graph)
    assert fused <= 0.99
