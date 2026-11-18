"""Pure value helpers shared by sensor entities and unit tests."""

from __future__ import annotations

import math
from typing import Any


def numeric_value(value: Any, *, non_negative: bool = False) -> float | None:
    """Convert valid numeric API values while rejecting NaN, infinity, and bad counters."""
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or (non_negative and numeric < 0):
        return None
    return numeric


def battery_directional_power(value: Any) -> tuple[float | None, float | None]:
    """Split signed battery power into charge and discharge using observed flow sign."""
    numeric = numeric_value(value)
    if numeric is None:
        return None, None
    return max(0.0, -numeric), max(0.0, numeric)
