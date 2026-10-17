import math
from typing import Optional

from .models import CameraDetection, MatchCandidate, RadarDetection
from .time_alignment_engine import within_window

LOCATION_NORMALIZATION_M = 20.0
DIRECTION_NORMALIZATION_DEG = 90.0


def _location_distance(a, b) -> float:
    if a.location is None or b.location is None:
        return float("inf")
    return math.hypot(a.location.x - b.location.x, a.location.y - b.location.y)


def _direction_diff(a_dir: Optional[float], b_dir: Optional[float]) -> float:
    if a_dir is None or b_dir is None:
        return 180.0
    diff = abs(a_dir - b_dir) % 360
    return min(diff, 360 - diff)


def score_match(camera: CameraDetection, radar: RadarDetection) -> MatchCandidate:
    """Weighted multi-factor score: timestamp, location, direction, confidence.
    Speed plausibility is folded in implicitly via the radar's own confidence —
    a radar return with an implausible speed for the observed object class
    should already carry a lower confidence_score from the sensor model."""
    time_delta = within_window(camera, radar)
    dist = _location_distance(camera, radar)
    direction_diff = _direction_diff(camera.direction_deg, radar.direction_deg)

    time_score = 1.0 if time_delta is not None else 0.0
    location_score = max(0.0, 1.0 - dist / LOCATION_NORMALIZATION_M)
    direction_score = max(0.0, 1.0 - direction_diff / DIRECTION_NORMALIZATION_DEG)
    confidence_score = (camera.confidence_score + radar.confidence_score) / 2

    association_score = round(
        0.35 * time_score + 0.30 * location_score + 0.20 * direction_score + 0.15 * confidence_score,
        3,
    )
    rationale = (
        f"time_score={time_score:.2f} (delta={time_delta}), "
        f"location_score={location_score:.2f} (distance={dist:.1f}m), "
        f"direction_score={direction_score:.2f} (diff={direction_diff:.1f} deg), "
        f"confidence_score={confidence_score:.2f}"
    )
    return MatchCandidate(
        radar_id=radar.id,
        camera_id=camera.id,
        association_score=association_score,
        rationale=rationale,
    )


def rank_candidates(camera: CameraDetection, radar_detections: list[RadarDetection]) -> list[MatchCandidate]:
    scored = [score_match(camera, r) for r in radar_detections]
    return sorted(scored, key=lambda c: c.association_score, reverse=True)
