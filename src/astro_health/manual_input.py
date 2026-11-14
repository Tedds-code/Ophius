
# Made in cooperation with ChatGPT
# File: src/astro_health/manual_input.py

import math

from datetime import datetime
from typing import Callable

from astro_health.models import MeasurementValue, Reading
from astro_health.reading_source import ReadingSource


class ManualInput(ReadingSource):
    """Temporary keyboard interface for development and testing."""

    def __init__(
        self,
        measurements: tuple[MeasurementValue, ...] | None = None,
        mission_day: int | None = None,
        timestamp: datetime | None = None,
        input_function: Callable[[str], str] = input,
        output_function: Callable[[str], None] = print,
    ):
        self.measurements = measurements
        self.mission_day = mission_day
        self.timestamp = timestamp
        self.input_function = input_function
        self.output_function = output_function

    def _ask_nonempty_text(self, prompt: str) -> str:
        while True:
            value = self.input_function(prompt).strip()

            if value:
                return value

            self.output_function(
                "Error: This field cannot be empty. Please try again."
            )

    def _ask_positive_integer(self, prompt: str) -> int:
        while True:
            raw_value = self.input_function(prompt).strip()

            try:
                value = int(raw_value)
            except ValueError:
                self.output_function(
                    "Error: Enter a whole number greater than zero."
                )
                continue

            if value <= 0:
                self.output_function(
                    "Error: The number must be greater than zero."
                )
                continue

            return value

    def _ask_mission_day(self) -> int | None:
        while True:
            raw_value = self.input_function(
                "Mission day (press Enter if unknown): "
            ).strip()

            if raw_value == "":
                return None

            try:
                value = int(raw_value)
            except ValueError:
                self.output_function(
                    "Error: Enter a non-negative whole number."
                )
                continue

            if value < 0:
                self.output_function(
                    "Error: Mission day cannot be negative."
                )
                continue

            return value

    def _ask_number(self, prompt: str) -> float:
        while True:
            raw_value = self.input_function(prompt).strip()

            try:
                value = float(raw_value)
            except ValueError:
                self.output_function(
                    "Error: Enter a valid numerical value."
                )
                continue

            if not math.isfinite(value):
                self.output_function(
                    "Error: The value must be a finite number."
                )
                continue

            return value

    def _collect_measurements(
        self,
    ) -> tuple[MeasurementValue, ...]:
        self.output_function(
            "\nManual measurement entry"
        )
        self.output_function(
            "Enter the requested information."
        )
        self.output_function(
            "If an entry is invalid, only that field will be repeated."
        )

        count = self._ask_positive_integer(
            "\nHow many measurements will you enter? "
        )

        measurements = []

        for index in range(1, count + 1):
            self.output_function(
                f"\nMeasurement {index} of {count}"
            )

            measurement_type = self._ask_nonempty_text(
                "Measurement name: "
            )

            value = self._ask_number(
                f"Enter value for {measurement_type}: "
            )

            unit = self._ask_nonempty_text(
                f"Unit for {measurement_type}: "
            )

            measurements.append(
                MeasurementValue(
                    measurement_type=measurement_type,
                    value=value,
                    unit=unit,
                )
            )

        return tuple(measurements)

    def read(self) -> Reading:
        """Return a reading, prompting if no measurements were supplied."""

        if self.measurements is None:
            mission_day = (
                self.mission_day
                if self.mission_day is not None
                else self._ask_mission_day()
            )

            measurements = self._collect_measurements()
        else:
            mission_day = self.mission_day
            measurements = self.measurements

        reading_arguments = {
            "source": "manual",
            "measurements": measurements,
            "mission_day": mission_day,
        }

        if self.timestamp is not None:
            reading_arguments["timestamp"] = self.timestamp

        return Reading(**reading_arguments)
