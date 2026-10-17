import networkx as nx

from .models import DataItem


class EvidenceDependencyGraph:
    """Tracks lineage (parent_data_ids) as a NetworkX DiGraph so the
    uncertainty engine can tell independent evidence from evidence that's
    really the same observation twice."""

    def __init__(self):
        self.graph = nx.DiGraph()

    def register(self, item: DataItem) -> None:
        self.graph.add_node(item.id, sensor_source=item.sensor_source.value, kind=type(item).__name__)
        for parent_id in item.parent_data_ids:
            self.graph.add_edge(parent_id, item.id)

    def are_independent(self, id_a: str, id_b: str) -> bool:
        """Two items are dependent if one is an ancestor of the other, or if
        they share any common ancestor (i.e. both were derived from the same
        underlying source)."""
        if id_a == id_b:
            return False
        if id_a not in self.graph or id_b not in self.graph:
            return True
        if nx.has_path(self.graph, id_a, id_b) or nx.has_path(self.graph, id_b, id_a):
            return False
        ancestors_a = nx.ancestors(self.graph, id_a) | {id_a}
        ancestors_b = nx.ancestors(self.graph, id_b) | {id_b}
        return ancestors_a.isdisjoint(ancestors_b)
