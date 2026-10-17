from fusion_compliance_loop.evidence_dependency_graph import EvidenceDependencyGraph
from fusion_compliance_loop.models import CameraDetection, RadarDetection


def test_unrelated_items_are_independent():
    graph = EvidenceDependencyGraph()
    a = CameraDetection(confidence_score=0.5)
    b = RadarDetection(confidence_score=0.5)
    graph.register(a)
    graph.register(b)
    assert graph.are_independent(a.id, b.id)


def test_child_of_parent_is_not_independent():
    graph = EvidenceDependencyGraph()
    a = CameraDetection(confidence_score=0.5)
    graph.register(a)
    b = RadarDetection(confidence_score=0.5, parent_data_ids=[a.id])
    graph.register(b)
    assert not graph.are_independent(a.id, b.id)


def test_shared_ancestor_makes_items_dependent():
    graph = EvidenceDependencyGraph()
    root = CameraDetection(confidence_score=0.5)
    graph.register(root)
    child_a = RadarDetection(confidence_score=0.5, parent_data_ids=[root.id])
    child_b = RadarDetection(confidence_score=0.5, parent_data_ids=[root.id])
    graph.register(child_a)
    graph.register(child_b)
    assert not graph.are_independent(child_a.id, child_b.id)
