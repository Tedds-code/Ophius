# Made in cooperation with ChatGPT
# File: tests/tests_validation.py

import unittest
from datetime import datetime, timezone

from astro_health.models import Reading, MeasurementValue
from astro_health.validation import validate_reading


class TestReadingValidation(unittest.TestCase):

    def make_reading(self, **overrides):
        values = {
            "source": "manual",
            "measurements": (
                MeasurementValue(
                    measurement_type="heart_rate",
                    value=75.0,
                    unit="bpm",
                ),
            ),
            "timestamp": datetime.now(timezone.utc),
        }

        values.update(overrides)
        return Reading(**values)

    def test_valid_reading_remains_unassessed(self):
        result = validate_reading(self.make_reading())

        self.assertTrue(result.is_valid)
        self.assertEqual(result.reading.quality, "unassessed")
        self.assertEqual(result.errors, ())

    def test_empty_source_is_invalid(self):
        result = validate_reading(self.make_reading(source=""))

        self.assertEqual(result.reading.quality, "invalid")
        self.assertIn("Source cannot be empty.", result.errors)

    def test_naive_timestamp_is_invalid(self):
        result = validate_reading(
            self.make_reading(timestamp=datetime(2026, 1, 1))
        )

        self.assertEqual(result.reading.quality, "invalid")

    def test_empty_measurement_collection_is_invalid(self):
        result = validate_reading(
            self.make_reading(measurements=())
        )

        self.assertEqual(result.reading.quality, "invalid")
        self.assertIn(
            "A reading must contain at least one measurement.",
            result.errors,
        )

    def test_empty_measurement_type_is_invalid(self):
        measurement = MeasurementValue("", 75.0, "bpm")

        result = validate_reading(
            self.make_reading(measurements=(measurement,))
        )

        self.assertEqual(result.reading.quality, "invalid")

    def test_non_finite_measurement_is_invalid(self):
        measurement = MeasurementValue(
            "heart_rate",
            float("nan"),
            "bpm",
        )

        result = validate_reading(
            self.make_reading(measurements=(measurement,))
        )

        self.assertEqual(result.reading.quality, "invalid")

    def test_boolean_measurement_value_is_invalid(self):
        measurement = MeasurementValue(
            "heart_rate",
            True,
            "bpm",
        )

        result = validate_reading(
            self.make_reading(measurements=(measurement,))
        )

        self.assertEqual(result.reading.quality, "invalid")

    def test_empty_measurement_unit_is_invalid(self):
        measurement = MeasurementValue(
            "heart_rate",
            75.0,
            "",
        )

        result = validate_reading(
            self.make_reading(measurements=(measurement,))
        )

        self.assertEqual(result.reading.quality, "invalid")

    def test_multiple_measurements_are_validated(self):
        measurements = (
            MeasurementValue("heart_rate", 75.0, "bpm"),
            MeasurementValue("oxygen_saturation", 98.0, "%"),
        )

        result = validate_reading(
            self.make_reading(measurements=measurements)
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.reading.measurements), 2)

    def test_invalid_result_does_not_modify_original(self):
        original = self.make_reading(source="")

        result = validate_reading(original)

        self.assertEqual(original.quality, "unassessed")
        self.assertEqual(result.reading.quality, "invalid")
        self.assertIsNotNone(result.reading.quality_reason)

    def test_multiple_structural_errors_are_reported(self):
        measurements = (
            MeasurementValue("", float("nan"), ""),
        )

        result = validate_reading(
            self.make_reading(
                source="",
                measurements=measurements,
            )
        )

        self.assertFalse(result.is_valid)
        self.assertGreaterEqual(len(result.errors), 4)


if __name__ == "__main__":
    unittest.main()