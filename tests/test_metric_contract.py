"""Independent, hand-calculated cases for the matching metric contract."""
from types import SimpleNamespace
import math
import pytest
from benchmarks.approaches import MissionOutcome
from benchmarks.metrics import compute_metrics


def case(identity, truth, prediction):
    mission = SimpleNamespace(mission_id=identity, camera=SimpleNamespace(id="camera"), tags=[],
                              ground_truth={"correct_match_radar_id": truth, "fields_that_must_be_blocked": []})
    outcome = MissionOutcome(identity, "test", prediction, set(), [], None)
    return mission, outcome


@pytest.mark.parametrize("truth,prediction,counts", [
    ("a", "a", (1, 0, 0, 0)), ("a", "b", (0, 1, 1, 0)),
    ("a", None, (0, 0, 1, 0)), (None, "b", (0, 1, 0, 0)), (None, None, (0, 0, 0, 1)),
])
def test_each_matching_outcome(truth, prediction, counts):
    m, o = case("one", truth, prediction)
    result = compute_metrics([m], [o])
    assert tuple(result[k] for k in ("true_positives", "false_positives", "false_negatives", "true_negatives")) == counts
    assert result["ground_truth_match_count"] == int(truth is not None)


def test_wrong_match_cannot_inflate_recall_by_shrinking_its_denominator():
    pairs = [case("correct", "a", "a"), case("wrong", "b", "c"), case("abstain", "d", None)]
    result = compute_metrics([m for m, _ in pairs], [o for _, o in pairs])
    assert result["precision"] == 0.5
    assert result["recall"] == round(1 / 3, 4)
    assert result["f1_score"] == 0.4
    assert result["wrong_match_count"] == 1


def test_misaligned_or_duplicated_records_are_rejected():
    m1, o1 = case("one", "a", "a")
    m2, o2 = case("two", "b", "b")
    with pytest.raises(ValueError, match="same mission order"):
        compute_metrics([m1, m2], [o2, o1])
    with pytest.raises(ValueError, match="duplicate"):
        compute_metrics([m1, m1], [o1, o1])
    with pytest.raises(ValueError, match="1:1"):
        compute_metrics([m1], [])


@pytest.mark.parametrize("latency", [-1, math.nan, math.inf])
def test_invalid_measurements_are_not_silently_reported(latency):
    m, o = case("one", "a", "a")
    o.latency_s = latency
    with pytest.raises(ValueError, match="latency"):
        compute_metrics([m], [o])
