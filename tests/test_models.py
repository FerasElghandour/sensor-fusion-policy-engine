from datetime import datetime, timezone

from fusion_compliance_loop.enums import ClassificationLevel, NetworkDomain
from fusion_compliance_loop.models import CameraDetection, Location, RadarDetection


def test_camera_detection_carries_required_envelope_fields():
    item = CameraDetection(
        timestamp=datetime.now(timezone.utc),
        location=Location(x=1.0, y=2.0),
        confidence_score=0.55,
    )
    assert item.id
    assert item.sensor_source.value == "camera"
    assert item.classification_level == ClassificationLevel.PUBLIC
    assert item.network_domain == NetworkDomain.OPEN
    assert item.parent_data_ids == []
    assert item.transformation_history == []


def test_radar_detection_defaults():
    item = RadarDetection(confidence_score=0.8)
    assert item.sensor_source.value == "radar"
    assert item.speed_mps is None
    assert item.raw_signal_signature is None


def test_confidence_score_bounds_enforced():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CameraDetection(confidence_score=1.5)
