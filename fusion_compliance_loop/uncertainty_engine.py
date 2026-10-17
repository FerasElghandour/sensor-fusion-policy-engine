from .evidence_dependency_graph import EvidenceDependencyGraph

MAX_FUSED_CONFIDENCE = 0.99


def fuse_confidence(
    confidence_a: float,
    id_a: str,
    confidence_b: float,
    id_b: str,
    graph: EvidenceDependencyGraph,
) -> tuple[float, str]:
    """Combine two confidence scores. Independent evidence compounds via
    noisy-OR; dependent evidence (shared lineage) is capped at the stronger
    single observation so duplicated evidence can never inflate confidence."""
    if graph.are_independent(id_a, id_b):
        fused = 1 - (1 - confidence_a) * (1 - confidence_b)
        explanation = (
            f"Evidence {id_a} and {id_b} are independent, so they are combined "
            f"with noisy-OR: 1-(1-{confidence_a:.2f})*(1-{confidence_b:.2f}) = {fused:.3f}."
        )
    else:
        fused = max(confidence_a, confidence_b)
        explanation = (
            f"Evidence {id_a} and {id_b} share a common source and are NOT "
            f"independent, so confidence is capped at the stronger single "
            f"observation ({fused:.3f}) instead of being compounded."
        )
    return round(min(fused, MAX_FUSED_CONFIDENCE), 3), explanation
