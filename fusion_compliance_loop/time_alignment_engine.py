from datetime import timedelta
from typing import Optional

from .models import DataItem

DEFAULT_WINDOW = timedelta(seconds=2)


def is_missing_timestamp(item: DataItem) -> bool:
    return item.timestamp is None


def within_window(a: DataItem, b: DataItem, window: timedelta = DEFAULT_WINDOW) -> Optional[float]:
    """Return the absolute time delta in seconds if both timestamps exist and
    fall within the alignment window, else None (treated as non-alignable)."""
    if a.timestamp is None or b.timestamp is None:
        return None
    delta = abs((a.timestamp - b.timestamp).total_seconds())
    return delta if delta <= window.total_seconds() else None
