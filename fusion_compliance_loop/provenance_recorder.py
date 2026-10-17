import networkx as nx
import json

from .db import get_connection
from .models import DataItem, FusionResult


class ProvenanceRecorder:
    """Builds a NetworkX provenance DAG in memory and mirrors every item and
    conclusion to SQLite, so any conclusion can be traced back to the raw
    inputs it was built from."""

    def __init__(self, db_path: str = ":memory:"):
        self.graph = nx.DiGraph()
        self.conn = get_connection(db_path)

    def record(self, item: DataItem, retain_payload: bool = True) -> None:
        self.graph.add_node(item.id, kind=type(item).__name__, sensor_source=item.sensor_source.value)
        for parent_id in item.parent_data_ids:
            self.graph.add_edge(parent_id, item.id)
        self.conn.execute(
            "INSERT OR REPLACE INTO provenance (id, kind, sensor_source, payload) VALUES (?, ?, ?, ?)",
            (item.id, type(item).__name__, item.sensor_source.value,
             item.model_dump_json() if retain_payload else json.dumps({"id": item.id, "rejected": True})),
        )
        self.conn.commit()

    def record_conclusion(self, result: FusionResult, contributing_ids: list[str]) -> None:
        self.graph.add_node(result.conclusion_id, kind="FusionResult")
        for cid in contributing_ids:
            self.graph.add_edge(cid, result.conclusion_id)
        self.conn.execute(
            "INSERT OR REPLACE INTO conclusions (id, payload) VALUES (?, ?)",
            (result.conclusion_id, result.model_dump_json()),
        )
        self.conn.commit()

    def trace_to_inputs(self, conclusion_id: str) -> list[str]:
        """All raw/derived data nodes that feed a conclusion, ordered."""
        if conclusion_id not in self.graph:
            return []
        return sorted(nx.ancestors(self.graph, conclusion_id))
