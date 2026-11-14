
# Made in cooperation with ChatGPT
# File: tests/test_health_service.py

import tempfile
import unittest

from pathlib import Path

from astro_health.database import Database
from astro_health.health_service import HealthService
from astro_health.manual_input import ManualInput
from astro_health.models import MeasurementValue, Reading


class TestHealthService(unittest.TestCase):

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = (
            Path(self.temporary_directory.name) / "test_health.db"
        )

        self.database = Database(database_path)
        self.database.initialize()

        self.service = HealthService(self.database)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_record_reading(self):
        reading = Reading(
            source="manual",
            measurements=(
                MeasurementValue(
                    "example_measurement",
                    42.0,
                    "example_unit",
                ),
            ),
        )

        reading_id = self.service.record_reading(reading)
        stored = self.service.get_reading(reading_id)

        self.assertIsNotNone(stored)
        self.assertEqual(stored.source, "manual")
        self.assertEqual(stored.measurements, reading.measurements)
        self.assertEqual(stored.quality, "unassessed")

    def test_record_from_manual_source(self):
        source = ManualInput(
            measurements=(
                MeasurementValue(
                    "example_measurement",
                    12.0,
                    "example_unit",
                ),
            ),
            mission_day=5,
        )

        reading_id = self.service.record_from_source(source)
        stored = self.service.get_reading(reading_id)

        self.assertIsNotNone(stored)
        self.assertEqual(stored.mission_day, 1)
        self.assertEqual(stored.source, "manual")

    def test_structurally_invalid_reading_is_preserved(self):
        reading = Reading(
            source="",
            measurements=(
                MeasurementValue(
                    "example_measurement",
                    10.0,
                    "example_unit",
                ),
            ),
        )

        reading_id = self.service.record_reading(reading)
        stored = self.service.get_reading(reading_id)

        self.assertIsNotNone(stored)
        self.assertEqual(stored.quality, "invalid")
        self.assertIn(
            "Source cannot be empty.",
            stored.quality_reason,
        )

    def test_nonexistent_reading_returns_none(self):
        self.assertIsNone(self.service.get_reading(999999))

    def test_invalid_source_type_is_rejected(self):
        with self.assertRaises(TypeError):
            self.service.record_from_source("not a source")

    def test_invalid_reading_type_is_rejected(self):
        with self.assertRaises(TypeError):
            self.service.record_reading("not a reading")

    def test_invalid_reading_id_is_rejected(self):
        with self.assertRaises(TypeError):
            self.service.get_reading(True)

        with self.assertRaises(ValueError):
            self.service.get_reading(0)


if __name__ == "__main__":
    unittest.main()
