# Made in cooperation with ChatGPT
# File: tests/test_reading.py

import unittest
from datetime import datetime

from astro_health.models import Reading, MeasurementValue


class TestReading(unittest.TestCase):

    def test_reading_can_contain_one_measurement(self):
        measurement = MeasurementValue(
            measurement_type="heart_rate",
            value=75.0,
            unit="bpm",
        )

        reading = Reading(
            source="manual",
            measurements=(measurement,),
        )

        self.assertEqual(reading.source, "manual")
        self.assertEqual(len(reading.measurements), 1)
        self.assertEqual(
            reading.measurements[0].measurement_type,
            "heart_rate",
        )
        self.assertEqual(reading.quality, "unassessed")

    def test_reading_can_contain_multiple_measurements(self):
        heart_rate = MeasurementValue(
            measurement_type="heart_rate",
            value=75.0,
            unit="bpm",
        )

        oxygen = MeasurementValue(
            measurement_type="oxygen_saturation",
            value=98.0,
            unit="%",
        )

        reading = Reading(
            source="pulse_oximeter",
            measurements=(heart_rate, oxygen),
        )

        self.assertEqual(len(reading.measurements), 2)

    def test_reading_is_immutable(self):
        reading = Reading(
            source="manual",
            measurements=(
                MeasurementValue("heart_rate", 75.0, "bpm"),
            ),
        )

        with self.assertRaises(AttributeError):
            reading.source = "sensor"

    def test_measurement_is_immutable(self):
        measurement = MeasurementValue(
            measurement_type="heart_rate",
            value=75.0,
            unit="bpm",
        )

        with self.assertRaises(AttributeError):
            measurement.value = 80.0

    def test_timestamp_is_generated_automatically(self):
        reading = Reading(
            source="manual",
            measurements=(
                MeasurementValue("heart_rate", 75.0, "bpm"),
            ),
        )

        self.assertIsInstance(reading.timestamp, datetime)
        self.assertIsNotNone(reading.timestamp.tzinfo)
        self.assertEqual(reading.timestamp.utcoffset().total_seconds(), 0)


if __name__ == "__main__":
    unittest.main()