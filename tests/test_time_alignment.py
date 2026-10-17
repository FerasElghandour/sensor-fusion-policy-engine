from datetime import datetime, timedelta, timezone

from fusion_compliance_loop.models import CameraDetection, RadarDetection
from fusion_compliance_loop.time_alignment_engine import is_missing_timestamp, within_window


def test_missing_timestamp_detected():
    item = CameraDetection(confidence_score=0.5)
    assert is_missing_timestamp(item)


def test_within_window_true_for_close_timestamps():
    t0 = datetime.now(timezone.utc)
    a = CameraDetection(timestamp=t0, confidence_score=0.5)
    b = RadarDetection(timestamp=t0 + timedelta(seconds=1), confidence_score=0.5)
    assert within_window(a, b) is not None


def test_within_window_false_for_delayed_data():
    t0 = datetime.now(timezone.utc)
    a = CameraDetection(timestamp=t0, confidence_score=0.5)
    b = RadarDetection(timestamp=t0 + timedelta(seconds=30), confidence_score=0.5)
    assert within_window(a, b) is None


def test_within_window_none_when_timestamp_missing():
    a = CameraDetection(confidence_score=0.5)
    b = RadarDetection(timestamp=datetime.now(timezone.utc), confidence_score=0.5)
    assert within_window(a, b) is None
