from enum import Enum


class SensorType(str, Enum):
    CAMERA = "camera"
    RADAR = "radar"


class ClassificationLevel(str, Enum):
    PUBLIC = "public"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"
    # Synthetic stand-in label for demonstration only. No real Protected B
    # data, systems, or accreditation are used or implied by this value —
    # see docs/THREAT_MODEL.md and application/EVIDENCE_GAPS.md.
    PROTECTED_B = "protected_b"
    CONFIDENTIAL = "confidential"


CLASSIFICATION_ORDER = [
    ClassificationLevel.PUBLIC,
    ClassificationLevel.SENSITIVE,
    ClassificationLevel.RESTRICTED,
    ClassificationLevel.PROTECTED_B,
    ClassificationLevel.CONFIDENTIAL,
]


class NetworkDomain(str, Enum):
    OPEN = "open"
    PARTNER = "partner"
    INTERNAL = "internal"
    RESTRICTED_NET = "restricted_net"
    # Two explicit synthetic network security domains, added to demonstrate
    # essential outcome #2 ("security domains... classification levels,
    # including at least Protected B") with unambiguous, non-generic names.
    # Simulated domains only — no real network security boundary exists.
    CANADA_PROTECTED = "canada_protected"
    COALITION_UNCLASSIFIED = "coalition_unclassified"


class PolicyAction(str, Enum):
    PERMIT = "PERMIT"
    RESTRICT = "RESTRICT"
    SEGREGATE = "SEGREGATE"
    REJECT = "REJECT"
    REQUIRE_REVIEW = "REQUIRE_REVIEW"
    # Distinct from RESTRICT: an explicit, accountable reclassification to a
    # lower sensitivity so (a reduced form of) the item may cross a domain it
    # would otherwise be blocked from. Only ever fires when a rule requires
    # and finds an explicit authorization marker (DataItem.downgrade_authorized_by)
    # — never on AI suspicion alone.
    DOWNGRADE = "DOWNGRADE"


class ObjectClass(str, Enum):
    VEHICLE = "vehicle"
    PEDESTRIAN = "pedestrian"
    UNKNOWN = "unknown"
