from dataclasses import dataclass, field
from typing import Optional

from .enums import SensorType
from .models import DataItem

# Which sensor type can supply which missing field.
FIELD_PROVIDERS: dict[str, SensorType] = {
    "speed_mps": SensorType.RADAR,
    "distance_m": SensorType.RADAR,
    "direction_deg": SensorType.RADAR,
    "object_class": SensorType.CAMERA,
}


@dataclass
class SensorRequestPlanner:
    """Detects missing fields on a data item, decides which sensor could
    resolve them, and enforces a hard cap on repeated requests so an
    evidence-seeking loop can't run forever."""

    max_requests: int = 3
    requests_made: int = 0
    request_log: list[str] = field(default_factory=list)

    def missing_fields(self, item: DataItem) -> list[str]:
        """A field counts as missing whether the item's own model never
        defines it (e.g. a CameraDetection has no speed_mps at all) or it's
        present but unset — both mean the loop needs another sensor."""
        data = item.model_dump()
        return [f for f in ("speed_mps", "distance_m") if data.get(f) is None]

    def plan_sensor(self, missing_fields: list[str]) -> Optional[SensorType]:
        for f in missing_fields:
            if f in FIELD_PROVIDERS:
                return FIELD_PROVIDERS[f]
        return None

    def request(self, missing_fields: list[str]) -> Optional[SensorType]:
        if not missing_fields:
            return None
        if self.requests_made >= self.max_requests:
            self.request_log.append(
                f"LIMIT_REACHED: {self.requests_made}/{self.max_requests} requests already made — "
                f"no further sensor requests issued for {missing_fields}"
            )
            return None
        sensor = self.plan_sensor(missing_fields)
        if sensor is not None:
            self.requests_made += 1
            self.request_log.append(
                f"Requested {sensor.value} data (request {self.requests_made}/{self.max_requests}) "
                f"to resolve missing {missing_fields}"
            )
        return sensor
