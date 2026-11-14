# Made in cooperation with ChatGPT
# File: src/astro_health/validation.py

import math

from dataclasses import dataclass, replace
from datetime import datetime

from astro_health.models import Reading, MeasurementValue


@dataclass(frozen=True)
class ValidationResult:
    """Result of structural validation."""

    reading: Reading
    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        """True when no structural errors were found."""
        return len(self.errors) == 0


def validate_reading(reading: Reading) -> ValidationResult:
    """
    Check the structure of a reading and its measurements.

    Structural errors produce a new reading labelled 'invalid'.
    Structurally valid readings remain 'unassessed'.

    This function does not determine medical validity.
    """

    errors = []

    # Check the reading object
    if not isinstance(reading, Reading):
        raise TypeError("Expected a Reading object.")

    # Check source
    if not isinstance(reading.source, str) or not reading.source.strip():
        errors.append("Source cannot be empty.")

    # Check timestamp
    if not isinstance(reading.timestamp, datetime):
        errors.append("Timestamp must be a datetime value.")
    elif (
        reading.timestamp.tzinfo is None
        or reading.timestamp.utcoffset() is None
    ):
        errors.append("Timestamp must include timezone information.")

    # Check mission day
    if reading.mission_day is not None:
        if (
            isinstance(reading.mission_day, bool)
            or not isinstance(reading.mission_day, int)
            or reading.mission_day < 0
        ):
            errors.append(
                "Mission day must be a non-negative integer."
            )

    # Check measurement collection
    if not isinstance(reading.measurements, tuple):
        errors.append("Measurements must be provided as a tuple.")

    elif len(reading.measurements) == 0:
        errors.append("A reading must contain at least one measurement.")

    else:
        # Check every individual measurement
        for index, measurement in enumerate(reading.measurements, start=1):

            if not isinstance(measurement, MeasurementValue):
                errors.append(
                    f"Measurement {index} must be a MeasurementValue object."
                )
                continue

            if (
                not isinstance(measurement.measurement_type, str)
                or not measurement.measurement_type.strip()
            ):
                errors.append(
                    f"Measurement {index}: type cannot be empty."
                )

            if (
                isinstance(measurement.value, bool)
                or not isinstance(measurement.value, (int, float))
                or not math.isfinite(measurement.value)
            ):
                errors.append(
                    f"Measurement {index}: value must be a finite number."
                )

            if (
                not isinstance(measurement.unit, str)
                or not measurement.unit.strip()
            ):
                errors.append(
                    f"Measurement {index}: unit cannot be empty."
                )

    # Create a new reading with its structural result.
    if errors:
        validated_reading = replace(
            reading,
            quality="invalid",
            quality_reason="; ".join(errors),
        )
    else:
        validated_reading = replace(
            reading,
            quality="unassessed",
            quality_reason=None,
        )

    return ValidationResult(
        reading=validated_reading,
        errors=tuple(errors),
    )