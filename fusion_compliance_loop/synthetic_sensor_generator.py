import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from .enums import ClassificationLevel, NetworkDomain, ObjectClass
from .models import CameraDetection, Location, RadarDetection


def make_camera_detection(
    confidence: float = 0.55,
    timestamp: Optional[datetime] = None,
    location: Optional[Location] = None,
    direction_deg: float = 90.0,
    classification_level: ClassificationLevel = ClassificationLevel.PUBLIC,
    release_permissions: Optional[list[NetworkDomain]] = None,
    network_domain: NetworkDomain = NetworkDomain.OPEN,
    **extra,
) -> CameraDetection:
    return CameraDetection(
        timestamp=timestamp or datetime.now(timezone.utc),
        location=location or Location(x=0.0, y=0.0),
        confidence_score=confidence,
        object_class=ObjectClass.VEHICLE,
        direction_deg=direction_deg,
        classification_level=classification_level,
        network_domain=network_domain,
        release_permissions=(
            release_permissions
            if release_permissions is not None
            else [NetworkDomain.OPEN, NetworkDomain.PARTNER, NetworkDomain.INTERNAL]
        ),
        **extra,
    )


def make_radar_pool(
    anchor_timestamp: datetime,
    anchor_location: Location,
    seed: Optional[int] = None,
) -> list[RadarDetection]:
    """Three synthetic radar candidates: one strong true match plus two
    distractors, matching scenario 1 in the architecture doc. The true match
    carries a RESTRICTED raw-signal field not released for the OPEN domain."""
    rng = random.Random(seed)
    offsets = [
        # (seconds_offset, distance_m, direction_offset_deg, confidence, classification, release_permissions)
        (0.5, 1.5, 5.0, 0.82, ClassificationLevel.RESTRICTED, [NetworkDomain.RESTRICTED_NET]),
        (3.0, 12.0, 40.0, 0.40, ClassificationLevel.PUBLIC, [NetworkDomain.OPEN]),
        (6.0, 25.0, 120.0, 0.30, ClassificationLevel.PUBLIC, [NetworkDomain.OPEN]),
    ]
    detections = []
    for dt_s, dist_m, dir_off, conf, classification, perms in offsets:
        detections.append(
            RadarDetection(
                timestamp=anchor_timestamp + timedelta(seconds=dt_s),
                location=Location(x=anchor_location.x + dist_m / 10, y=anchor_location.y + dist_m / 10),
                confidence_score=conf,
                speed_mps=round(rng.uniform(8, 20), 1),
                distance_m=dist_m,
                direction_deg=(90.0 + dir_off) % 360,
                classification_level=classification,
                network_domain=NetworkDomain.OPEN,
                release_permissions=perms,
                raw_signal_signature=f"sig-{rng.randint(1000, 9999)}" if classification != ClassificationLevel.PUBLIC else None,
            )
        )
    return detections
