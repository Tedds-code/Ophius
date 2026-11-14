# Made in cooperation with ChatGPT
# File: src/astro_health/models.py

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass(frozen=True)
class MeasurementValue:
    """One individual numerical measurement."""

    measurement_type: str
    value: float
    unit: str


@dataclass(frozen=True)
class Reading:
    """One measurement event, which can contain multiple values."""

    source: str
    measurements: tuple[MeasurementValue, ...]

    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    mission_day: int | None = None

    quality: Literal[
        "unassessed",
        "ok",
        "suspect",
        "invalid",
    ] = "unassessed"

    quality_reason: str | None = None
    id: int | None = None