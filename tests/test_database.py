
# Made in cooperation with ChatGPT
# File: tests/test_database.py

import sqlite3
import tempfile
import unittest

from pathlib import Path

from astro_health.database import Database
from astro_health.models import MeasurementValue, Reading


class TestDatabase(unittest.TestCase):

    def setUp(self):
        """Create a fresh temporary database for each test."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "test_health.db"
        )

        self.database = Database(self.database_path)
        self.database.initialize()

    def tearDown(self):
        """Remove the temporary database after each test."""
        self.temporary_directory.cleanup()

    def test_database_file_is_created(self):
        self.assertTrue(self.database_path.exists())

    def test_save_and_retrieve_reading(self):
        original = Reading(
            source="manual",
            measurements=(
                MeasurementValue(
                    measurement_type="example_measurement",
                    value=42.0,
                    unit="example_unit",
                ),
            ),
            mission_day=3,
        )

        reading_id = self.database.save_reading(original)
        retrieved = self.database.get_reading(reading_id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, reading_id)
        self.assertEqual(retrieved.source, "manual")
        self.assertEqual(retrieved.mission_day, 3)
        self.assertEqual(retrieved.timestamp, original.timestamp)
        self.assertEqual(retrieved.quality, "unassessed")
        self.assertEqual(retrieved.measurements, original.measurements)

    def test_multiple_measurements_are_preserved(self):
        original = Reading(
            source="manual",
            measurements=(
                MeasurementValue("measurement_a", 10.0, "unit_a"),
                MeasurementValue("measurement_b", 20.0, "unit_b"),
            ),
        )

        reading_id = self.database.save_reading(original)
        retrieved = self.database.get_reading(reading_id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(len(retrieved.measurements), 2)
        self.assertEqual(
            retrieved.measurements,
            original.measurements,
        )

    def test_invalid_reading_is_stored_with_reason(self):
        original = Reading(
            source="",
            measurements=(
                MeasurementValue("measurement_a", 10.0, "unit_a"),
            ),
        )

        reading_id = self.database.save_reading(original)
        retrieved = self.database.get_reading(reading_id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.quality, "invalid")
        self.assertIn(
            "Source cannot be empty.",
            retrieved.quality_reason,
        )

        # Saving must not modify the original frozen object.
        self.assertEqual(original.quality, "unassessed")

    def test_nonexistent_reading_returns_none(self):
        retrieved = self.database.get_reading(999999)
        self.assertIsNone(retrieved)

   
    def test_schema_version_is_recorded(self):
        connection = sqlite3.connect(self.database_path)

        try:
            row = connection.execute(
                "SELECT version FROM schema_migrations"
            ).fetchone()
        finally:
            connection.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], 1)


if __name__ == "__main__":
    unittest.main()
