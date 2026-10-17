"""AI compliance-risk detector.

A second, small, explainable classifier (logistic regression) — separate
from ai_entity_association.py — that scores a single ingested item's
metadata for compliance risk: does this record look like it might carry a
classification, provenance, or cross-domain problem?

It is trained on synthetic data only, and it is purely advisory, exactly
like the entity-association model: it never permits, rejects, segregates,
or downgrades anything itself. Its `risk_probability` can make one specific,
policy-author-written rule condition (`requires_ai_risk_at_least`) become
eligible to match in policy_engine.py, and that rule can only ever be
configured to escalate toward a stricter disposition (e.g. an otherwise
DEFAULT_PERMIT case becoming REQUIRE_REVIEW) — never to loosen a
higher-priority deterministic rule's decision, since rule priority order is
evaluated identically regardless of what the AI says. See
docs/MODEL_CARD.md and application/TECHNICAL_CONCEPT.md for the full
"AI interprets, policy decides" architecture this preserves.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .enums import ClassificationLevel, NetworkDomain, ObjectClass, SensorType
from .models import ComplianceRiskAssessment, DataItem

# One feature per risk category named in the essential-outcome-1 spec.
RISK_FEATURE_NAMES = [
    "missing_classification_marking",
    "missing_domain_of_origin",
    "missing_release_authority",
    "classification_field_mismatch",
    "suspicious_classification_downgrade",
    "provenance_gap",
    "unexpected_transformation_history",
    "source_destination_domain_conflict",
    "restricted_field_pattern_in_transformed_record",
    "metadata_sensor_type_mismatch",
]

_RISK_LABELS = {
    "missing_classification_marking": "Missing classification marking",
    "missing_domain_of_origin": "Missing domain of origin",
    "missing_release_authority": "Missing release authority",
    "classification_field_mismatch": "Classification inconsistent with field contents",
    "suspicious_classification_downgrade": "Suspicious classification downgrade",
    "provenance_gap": "Provenance gap",
    "unexpected_transformation_history": "Unexpected transformation history",
    "source_destination_domain_conflict": "Source/destination domain conflict",
    "restricted_field_pattern_in_transformed_record": "Restricted field hidden inside a transformed record",
    "metadata_sensor_type_mismatch": "Metadata pattern inconsistent with sensor type",
}

# A feature is treated as a "detected risk category" once it crosses this
# value — deliberately most features are naturally 0.0/1.0 booleans, so 0.5
# is an unambiguous midpoint; the two continuous features (transformation
# history length, domain conflict) use the same cut.
_CATEGORY_DETECTION_THRESHOLD = 0.5


def _field_mismatch(item: DataItem, field_sensitivity_map: dict) -> bool:
    """Mirrors policy_engine's own field-sensitivity-mismatch check so the
    risk model's opinion and the deterministic rule's opinion are computed
    the same way — the risk model is a second, AI-driven signal about the
    same underlying question, not an unrelated heuristic."""
    from .enums import CLASSIFICATION_ORDER

    for f, true_level in field_sensitivity_map.items():
        if getattr(item, f, None) is not None and CLASSIFICATION_ORDER.index(item.classification_level) < CLASSIFICATION_ORDER.index(true_level):
            return True
    return False


def extract_risk_features(
    item: DataItem,
    field_sensitivity_map: Optional[dict] = None,
    target_domain: Optional[NetworkDomain] = None,
) -> dict:
    """Build the 10-feature risk vector for a single item. All ten map
    1:1 onto the risk categories essential outcome #1 asks the AI to detect."""
    field_sensitivity_map = field_sensitivity_map or {}

    missing_classification_marking = 0.0 if item.classification_marking_present else 1.0
    missing_domain_of_origin = 0.0 if item.domain_of_origin_marking_present else 1.0
    missing_release_authority = (
        1.0
        if (not item.release_authority_marking_present) or (not item.release_permissions)
        else 0.0
    )
    classification_field_mismatch = 1.0 if _field_mismatch(item, field_sensitivity_map) else 0.0

    downgrade_tokens = ("downgrade", "reclassif")
    has_downgrade_history = any(any(tok in entry.lower() for tok in downgrade_tokens) for entry in item.transformation_history)
    suspicious_classification_downgrade = 1.0 if (has_downgrade_history and not item.downgrade_authorized_by) else 0.0

    provenance_gap = 1.0 if (item.parent_data_ids and not item.transformation_history) else 0.0
    unexpected_transformation_history = min(1.0, len(item.transformation_history) / 5.0)

    source_destination_domain_conflict = 0.0
    if target_domain is not None and item.network_domain != target_domain and target_domain not in item.release_permissions:
        source_destination_domain_conflict = 1.0

    has_a_tracked_sensitive_field = any(
        getattr(item, f, None) is not None for f in ("raw_signal_signature", "facial_recognition_signature")
    )
    restricted_field_pattern_in_transformed_record = (
        1.0 if (has_a_tracked_sensitive_field and item.transformation_history) else 0.0
    )

    metadata_sensor_type_mismatch = 0.0
    if item.sensor_source == SensorType.RADAR:
        if getattr(item, "speed_mps", None) is None and getattr(item, "distance_m", None) is None:
            metadata_sensor_type_mismatch = 1.0
    elif item.sensor_source == SensorType.CAMERA:
        if getattr(item, "direction_deg", None) is None and getattr(item, "object_class", ObjectClass.UNKNOWN) == ObjectClass.UNKNOWN:
            metadata_sensor_type_mismatch = 1.0

    return {
        "missing_classification_marking": missing_classification_marking,
        "missing_domain_of_origin": missing_domain_of_origin,
        "missing_release_authority": missing_release_authority,
        "classification_field_mismatch": classification_field_mismatch,
        "suspicious_classification_downgrade": suspicious_classification_downgrade,
        "provenance_gap": provenance_gap,
        "unexpected_transformation_history": unexpected_transformation_history,
        "source_destination_domain_conflict": source_destination_domain_conflict,
        "restricted_field_pattern_in_transformed_record": restricted_field_pattern_in_transformed_record,
        "metadata_sensor_type_mismatch": metadata_sensor_type_mismatch,
    }


def generate_training_examples(n: int = 4000, seed: int = 43) -> tuple[np.ndarray, np.ndarray]:
    """Synthetic-only training data: two generating processes ("clean
    metadata" / "risky metadata") over the 10 features above, with 5% label
    noise so the boundary must be learned, matching the pattern in
    ai_entity_association.generate_training_examples."""
    rng = np.random.default_rng(seed)
    n_risky = n // 2
    n_clean = n - n_risky

    def bernoulli(p, size):
        return (rng.random(size) < p).astype(float)

    def clip01(x):
        return np.clip(x, 0.0, 1.0)

    risky = np.column_stack(
        [
            bernoulli(0.55, n_risky),  # missing_classification_marking
            bernoulli(0.45, n_risky),  # missing_domain_of_origin
            bernoulli(0.5, n_risky),  # missing_release_authority
            bernoulli(0.5, n_risky),  # classification_field_mismatch
            bernoulli(0.3, n_risky),  # suspicious_classification_downgrade
            bernoulli(0.35, n_risky),  # provenance_gap
            clip01(np.abs(rng.normal(0.6, 0.25, n_risky))),  # unexpected_transformation_history
            bernoulli(0.5, n_risky),  # source_destination_domain_conflict
            bernoulli(0.4, n_risky),  # restricted_field_pattern_in_transformed_record
            bernoulli(0.3, n_risky),  # metadata_sensor_type_mismatch
        ]
    )
    clean = np.column_stack(
        [
            bernoulli(0.03, n_clean),
            bernoulli(0.03, n_clean),
            bernoulli(0.05, n_clean),
            bernoulli(0.02, n_clean),
            bernoulli(0.01, n_clean),
            bernoulli(0.03, n_clean),
            clip01(np.abs(rng.normal(0.1, 0.1, n_clean))),
            bernoulli(0.03, n_clean),
            bernoulli(0.02, n_clean),
            bernoulli(0.05, n_clean),
        ]
    )

    X = np.vstack([risky, clean])
    y = np.concatenate([np.ones(n_risky), np.zeros(n_clean)])

    flip_mask = rng.random(len(y)) < 0.05
    y[flip_mask] = 1 - y[flip_mask]

    order = rng.permutation(len(y))
    return X[order], y[order]


@dataclass
class RiskPrediction:
    risk_probability: float
    risk_categories: list = field(default_factory=list)
    contributing_factors: list = field(default_factory=list)
    confidence: float = 0.0
    explanation: str = ""


class ComplianceRiskModel:
    """Logistic regression over the 10 risk features above. Deliberately
    simple and inspectable, mirroring ai_entity_association.EntityAssociationModel."""

    def __init__(self):
        self.scaler = StandardScaler()
        self.model = LogisticRegression(max_iter=1000)
        self.trained = False
        self.train_accuracy: Optional[float] = None
        self.holdout_accuracy: Optional[float] = None

    def train(self, n_samples: int = 4000, seed: int = 43, test_fraction: float = 0.2) -> "ComplianceRiskModel":
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

    def predict(self, features: dict) -> RiskPrediction:
        if not self.trained:
            self.train()
        x = np.array([[features[name] for name in RISK_FEATURE_NAMES]])
        x_scaled = self.scaler.transform(x)
        proba = float(self.model.predict_proba(x_scaled)[0][1])

        categories = [name for name in RISK_FEATURE_NAMES if features[name] >= _CATEGORY_DETECTION_THRESHOLD]
        contributing = self._contributing_factors(features, x_scaled[0])
        confidence = round(abs(proba - 0.5) * 2, 4)
        explanation = self._explain(proba, categories)

        return RiskPrediction(
            risk_probability=round(proba, 4),
            risk_categories=categories,
            contributing_factors=contributing,
            confidence=confidence,
            explanation=explanation,
        )

    def _contributing_factors(self, features: dict, x_scaled_row: np.ndarray) -> list:
        coefs = self.model.coef_[0]
        contributions = coefs * x_scaled_row
        order = np.argsort(-np.abs(contributions))
        lines = []
        for idx in order[:4]:
            name = RISK_FEATURE_NAMES[idx]
            direction = "toward RISK" if contributions[idx] > 0 else "toward CLEAN"
            lines.append(f"{_RISK_LABELS[name]} ({features[name]:.2f}) pushed {direction}, weight {contributions[idx]:+.2f}")
        return lines

    @staticmethod
    def _explain(proba: float, categories: list) -> str:
        if categories:
            names = ", ".join(_RISK_LABELS[c] for c in categories)
            return f"Compliance-risk probability {proba:.0%}. Detected risk categories: {names}."
        return f"Compliance-risk probability {proba:.0%}. No specific risk category crossed the detection threshold."

    def assess(
        self,
        item: DataItem,
        field_sensitivity_map: Optional[dict] = None,
        target_domain: Optional[NetworkDomain] = None,
    ) -> ComplianceRiskAssessment:
        features = extract_risk_features(item, field_sensitivity_map, target_domain)
        prediction = self.predict(features)
        return ComplianceRiskAssessment(
            risk_probability=prediction.risk_probability,
            risk_categories=prediction.risk_categories,
            contributing_factors=prediction.contributing_factors,
            confidence=prediction.confidence,
            explanation=prediction.explanation,
        )


@lru_cache(maxsize=1)
def get_default_risk_model() -> ComplianceRiskModel:
    """Module-level singleton, trained once with a fixed seed for
    reproducibility — mirrors ai_entity_association.get_default_model."""
    return ComplianceRiskModel().train()
