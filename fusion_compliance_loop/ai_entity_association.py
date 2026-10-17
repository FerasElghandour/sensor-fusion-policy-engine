"""model-based entity association.

A small, explainable classifier (logistic regression) that predicts whether
a camera and radar observation describe the same real-world object. It is
trained on synthetic data only, and it is purely advisory: it may recommend
which candidate to fuse, but fusion_engine.py always routes the recommended
candidate through the same deterministic policy_engine before any data is
actually combined. The AI never decides what is permitted — it only
proposes what might match.

The deterministic entity_association_engine.rank_candidates() remains the
system's baseline scorer and is untouched by this module.
"""

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .models import CameraDetection, RadarDetection

FEATURE_NAMES = [
    "time_diff_s",
    "distance_diff_m",
    "direction_diff_deg",
    "speed_plausibility_diff",
    "sensor_confidence",
    "object_type_similarity",
    "data_completeness",
    "sensor_reliability",
]

_FEATURE_LABELS = {
    "time_diff_s": "Time difference",
    "distance_diff_m": "Location distance",
    "direction_diff_deg": "Direction difference",
    "speed_plausibility_diff": "Speed implausibility",
    "sensor_confidence": "Average sensor confidence",
    "object_type_similarity": "Object-type consistency",
    "data_completeness": "Data completeness",
    "sensor_reliability": "Sensor platform reliability",
}

# Static, synthetic per-sensor-platform reliability — distinct from a single
# observation's confidence_score, this represents how much the platform class
# is trusted in general (a fixed, non-learned prior).
SENSOR_RELIABILITY = {"camera": 0.85, "radar": 0.92}

PLAUSIBLE_SPEED_BANDS_MPS = {
    "vehicle": (2.0, 40.0),
    "pedestrian": (0.0, 3.0),
    "unknown": (0.0, 40.0),
}


def _band_deviation(speed: float, band: tuple[float, float]) -> float:
    lo, hi = band
    if speed < lo:
        return lo - speed
    if speed > hi:
        return speed - hi
    return 0.0


def extract_features(camera: CameraDetection, radar: RadarDetection) -> dict:
    """Build the 8-feature vector the model was trained on. Missing data
    is never imputed to look favorable — it's scored as a large gap."""
    if camera.timestamp is not None and radar.timestamp is not None:
        time_diff_s = abs((camera.timestamp - radar.timestamp).total_seconds())
    else:
        time_diff_s = 999.0

    if camera.location is not None and radar.location is not None:
        distance_diff_m = ((camera.location.x - radar.location.x) ** 2 + (camera.location.y - radar.location.y) ** 2) ** 0.5
    else:
        distance_diff_m = 999.0

    if camera.direction_deg is not None and radar.direction_deg is not None:
        diff = abs(camera.direction_deg - radar.direction_deg) % 360
        direction_diff_deg = min(diff, 360 - diff)
    else:
        direction_diff_deg = 180.0

    band = PLAUSIBLE_SPEED_BANDS_MPS.get(camera.object_class.value, PLAUSIBLE_SPEED_BANDS_MPS["unknown"])
    if radar.speed_mps is not None:
        deviation = _band_deviation(radar.speed_mps, band)
        speed_plausibility_diff = deviation
        object_type_similarity = max(0.0, 1.0 - deviation / 20.0)
    else:
        speed_plausibility_diff = 20.0
        object_type_similarity = 0.5

    sensor_confidence = (camera.confidence_score + radar.confidence_score) / 2

    tracked_fields = [
        camera.timestamp,
        camera.location,
        camera.direction_deg,
        radar.timestamp,
        radar.location,
        radar.direction_deg,
        radar.speed_mps,
        radar.distance_m,
    ]
    data_completeness = sum(1 for f in tracked_fields if f is not None) / len(tracked_fields)

    sensor_reliability = (SENSOR_RELIABILITY["camera"] + SENSOR_RELIABILITY["radar"]) / 2

    return {
        "time_diff_s": time_diff_s,
        "distance_diff_m": distance_diff_m,
        "direction_diff_deg": direction_diff_deg,
        "speed_plausibility_diff": speed_plausibility_diff,
        "sensor_confidence": sensor_confidence,
        "object_type_similarity": object_type_similarity,
        "data_completeness": data_completeness,
        "sensor_reliability": sensor_reliability,
    }


def generate_training_examples(n: int = 4000, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Synthetic-only training data: two overlapping generating processes
    (true match / true non-match) with Gaussian noise and 5% label noise, so
    the boundary has to be learned rather than trivially separable."""
    rng = np.random.default_rng(seed)
    n_match = n // 2
    n_nonmatch = n - n_match

    def clip(values, lo, hi):
        return np.clip(values, lo, hi)

    match_time = clip(np.abs(rng.normal(0.5, 0.6, n_match)), 0, None)
    match_dist = clip(np.abs(rng.normal(2.0, 3.0, n_match)), 0, None)
    match_dir = clip(np.abs(rng.normal(10, 15, n_match)), 0, 180)
    match_speed = clip(np.abs(rng.normal(1.0, 3.0, n_match)), 0, None)
    match_conf = rng.uniform(0.5, 0.95, n_match)
    match_type_sim = rng.uniform(0.6, 1.0, n_match)
    match_complete = rng.uniform(0.7, 1.0, n_match)
    match_reliab = rng.uniform(0.8, 0.92, n_match)

    nomatch_time = clip(np.abs(rng.normal(8.0, 6.0, n_nonmatch)), 0, None)
    nomatch_dist = clip(np.abs(rng.normal(30.0, 20.0, n_nonmatch)), 0, None)
    nomatch_dir = clip(np.abs(rng.normal(90, 50, n_nonmatch)), 0, 180)
    nomatch_speed = clip(np.abs(rng.normal(15.0, 10.0, n_nonmatch)), 0, None)
    nomatch_conf = rng.uniform(0.2, 0.8, n_nonmatch)
    nomatch_type_sim = rng.uniform(0.0, 0.6, n_nonmatch)
    nomatch_complete = rng.uniform(0.3, 0.9, n_nonmatch)
    nomatch_reliab = rng.uniform(0.8, 0.92, n_nonmatch)

    X = np.vstack(
        [
            np.column_stack([match_time, match_dist, match_dir, match_speed, match_conf, match_type_sim, match_complete, match_reliab]),
            np.column_stack([nomatch_time, nomatch_dist, nomatch_dir, nomatch_speed, nomatch_conf, nomatch_type_sim, nomatch_complete, nomatch_reliab]),
        ]
    )
    y = np.concatenate([np.ones(n_match), np.zeros(n_nonmatch)])

    # 5% label noise so the classes overlap realistically.
    flip_mask = rng.random(len(y)) < 0.05
    y[flip_mask] = 1 - y[flip_mask]

    order = rng.permutation(len(y))
    return X[order], y[order]


@dataclass
class MatchPrediction:
    match_probability: float
    predicted_match: bool
    explanation: list[str] = field(default_factory=list)


class EntityAssociationModel:
    """Logistic regression over the 8 features above. Deliberately simple
    and inspectable — coefficients times scaled feature values give an
    additive, human-readable explanation for every prediction."""

    def __init__(self):
        self.scaler = StandardScaler()
        self.model = LogisticRegression(max_iter=1000)
        self.trained = False
        self.train_accuracy: float | None = None
        self.holdout_accuracy: float | None = None

    def train(self, n_samples: int = 4000, seed: int = 42, test_fraction: float = 0.2) -> "EntityAssociationModel":
        X, y = generate_training_examples(n_samples, seed)
        split = int(len(X) * (1 - test_fraction))
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        self.scaler.fit(X_train)
        X_train_scaled = self.scaler.transform(X_train)
        self.model.fit(X_train_scaled, y_train)

        self.train_accuracy = float(self.model.score(X_train_scaled, y_train))
        self.holdout_accuracy = float(self.model.score(self.scaler.transform(X_test), y_test))
        self.trained = True
        return self

    def predict(self, features: dict, threshold: float = 0.5) -> MatchPrediction:
        if not self.trained:
            self.train()
        x = np.array([[features[name] for name in FEATURE_NAMES]])
        x_scaled = self.scaler.transform(x)
        proba = float(self.model.predict_proba(x_scaled)[0][1])
        return MatchPrediction(
            match_probability=round(proba, 4),
            predicted_match=proba >= threshold,
            explanation=self._explain(features, x_scaled[0]),
        )

    def _explain(self, features: dict, x_scaled_row: np.ndarray) -> list[str]:
        coefs = self.model.coef_[0]
        contributions = coefs * x_scaled_row
        order = np.argsort(-np.abs(contributions))
        lines = []
        for idx in order[:4]:
            name = FEATURE_NAMES[idx]
            direction = "toward MATCH" if contributions[idx] > 0 else "toward NON-MATCH"
            lines.append(f"{_FEATURE_LABELS[name]} ({features[name]:.2f}) pushed {direction}, weight {contributions[idx]:+.2f}")
        return lines


@lru_cache(maxsize=1)
def get_default_model() -> EntityAssociationModel:
    """Module-level singleton, trained once with a fixed seed for
    reproducibility. Call EntityAssociationModel().train(...) directly if a
    fresh, differently-seeded model is needed instead."""
    return EntityAssociationModel().train()


def ai_rank_candidates(
    camera: CameraDetection,
    radar_detections: list[RadarDetection],
    model: EntityAssociationModel | None = None,
) -> list[tuple[RadarDetection, MatchPrediction, dict]]:
    """Additive, explainable alternative to entity_association_engine.rank_candidates().
    Returns (radar, prediction, features) tuples sorted by match_probability,
    highest first. This function only recommends — it never touches
    policy_engine or fusion_engine's confidence math directly."""
    model = model or get_default_model()
    scored = []
    for radar in radar_detections:
        features = extract_features(camera, radar)
        prediction = model.predict(features)
        scored.append((radar, prediction, features))
    scored.sort(key=lambda t: t[1].match_probability, reverse=True)
    return scored
