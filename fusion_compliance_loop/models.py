import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from .enums import ClassificationLevel, NetworkDomain, ObjectClass, PolicyAction, SensorType


def new_id() -> str:
    return str(uuid.uuid4())


class Location(BaseModel):
    x: float
    y: float


class DataItem(BaseModel):
    """Base envelope every piece of sensor/derived data must carry."""

    id: str = Field(default_factory=new_id)
    sensor_source: SensorType
    timestamp: Optional[datetime] = None
    location: Optional[Location] = None
    classification_level: ClassificationLevel = ClassificationLevel.PUBLIC
    network_domain: NetworkDomain = NetworkDomain.OPEN
    release_permissions: list[NetworkDomain] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    parent_data_ids: list[str] = Field(default_factory=list)
    transformation_history: list[str] = Field(default_factory=list)

    # v0.3 (compliance-risk audit): explicit metadata-presence markers, kept
    # distinct from classification_level/network_domain/release_permissions
    # themselves so "this record has no classification marking at all" is a
    # genuine, representable condition rather than being conflated with "this
    # record declares classification_level=PUBLIC." Default True (normal,
    # complete metadata) — set False only to simulate a missing-marking
    # condition.
    classification_marking_present: bool = True
    domain_of_origin_marking_present: bool = True
    release_authority_marking_present: bool = True

    # Accountability marker for an authorized reclassification-to-lower-
    # sensitivity action (PolicyAction.DOWNGRADE). None/empty means no
    # authorization is on file, so any rule requiring it will not match.
    # This is a synthetic accountability record only — it is not backed by
    # real authentication or identity verification.
    downgrade_authorized_by: Optional[str] = None


class CameraDetection(DataItem):
    sensor_source: SensorType = SensorType.CAMERA
    object_class: ObjectClass = ObjectClass.UNKNOWN
    direction_deg: Optional[float] = None
    bounding_box_area: Optional[float] = None
    # Camera's own sensitive-field analogue to RadarDetection.raw_signal_signature
    # — added so field-level enforcement is symmetric across both sensor
    # modalities (see policies/default_policy.yaml field_sensitivity_map).
    facial_recognition_signature: Optional[str] = None


class RadarDetection(DataItem):
    sensor_source: SensorType = SensorType.RADAR
    speed_mps: Optional[float] = None
    distance_m: Optional[float] = None
    direction_deg: Optional[float] = None
    raw_signal_signature: Optional[str] = None


class MatchCandidate(BaseModel):
    radar_id: str
    camera_id: str
    association_score: float
    rationale: str


class PolicyDecision(BaseModel):
    data_id: str
    action: PolicyAction
    rule_name: str
    blocked_fields: list[str] = Field(default_factory=list)
    explanation: str
    # v0.2: every decision is traceable to the exact policy artifact that produced it.
    policy_id: str = ""
    policy_version: str = ""
    rule_version: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def reason(self) -> str:
        """Alias matching the "Reason" field named in the compliance spec."""
        return self.explanation


class ComplianceRiskAssessment(BaseModel):
    """Output of the AI compliance-risk detector (ai_compliance_risk.py).
    Advisory only — see that module's docstring for why this can never
    itself permit, reject, segregate, or downgrade data."""

    risk_probability: float
    risk_categories: list[str] = Field(default_factory=list)
    contributing_factors: list[str] = Field(default_factory=list)
    confidence: float
    explanation: str


class FusionResult(BaseModel):
    conclusion_id: str = Field(default_factory=new_id)
    object_class: ObjectClass
    confidence_before: float
    confidence_after: float
    contributing_data_ids: list[str]
    # Kept exactly as before (the winning radar candidate's rule only) for
    # backward compatibility with existing callers that assume
    # applied_policy_rules[-1] is that decision (e.g. benchmarks/approaches.py).
    blocked_fields: list[str]
    applied_policy_rules: list[str]
    requested_evidence: list[str]
    candidates_considered: list[MatchCandidate] = Field(default_factory=list)
    explanation: str

    # v0.3 (compliance-risk audit): every ingested item — camera AND every
    # radar candidate, not just the one selected for fusion — now receives
    # its own independent compliance disposition. These fields are additive;
    # nothing above this line changed meaning.
    camera_compliance_decision_id: str = ""
    camera_policy_rule: str = ""
    camera_policy_id: str = ""
    camera_policy_version: str = ""
    camera_blocked_fields: list[str] = Field(default_factory=list)
    camera_ai_risk_probability: float = 0.0
    camera_approved: bool = True
    radar_dispositions: list[dict] = Field(default_factory=list)
