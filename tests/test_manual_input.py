
# Made in cooperation with ChatGPT
# File: tests/test_manual_input.py

import unittest

from datetime import datetime, timezone

from astro_health.manual_input import ManualInput
from astro_health.models import MeasurementValue, Reading
from astro_health.reading_source import ReadingSource


class TestManualInput(unittest.TestCase):

    def setUp(self):
        self.measurements = (
            MeasurementValue(
                measurement_type="example_measurement",
                value=42.0,
                unit="example_unit",
            ),
        )

    def test_manual_input_is_reading_source(self):
        manual_input = ManualInput(self.measurements)

        self.assertIsInstance(manual_input, ReadingSource)

    def test_read_returns_reading(self):
        manual_input = ManualInput(self.measurements)
        reading = manual_input.read()

        self.assertIsInstance(reading, Reading)
        self.assertEqual(reading.source, "manual")
        self.assertEqual(reading.measurements, self.measurements)
        self.assertEqual(reading.quality, "unassessed")

    def test_timestamp_is_generated_automatically(self):
        manual_input = ManualInput(self.measurements)
        reading = manual_input.read()

        self.assertIsInstance(reading.timestamp, datetime)
        self.assertIsNotNone(reading.timestamp.tzinfo)
        self.assertEqual(reading.timestamp.utcoffset().total_seconds(), 0)

    def test_supplied_timestamp_is_preserved(self):
        historical_timestamp = datetime(
            2026, 1, 15, 14, 30, tzinfo=timezone.utc
        )

        manual_input = ManualInput(
            self.measurements,
            timestamp=historical_timestamp,
        )
        reading = manual_input.read()

        self.assertEqual(reading.timestamp, historical_timestamp)

    def test_mission_day_is_preserved(self):
        manual_input = ManualInput(
            self.measurements,
            mission_day=7,
        )
        reading = manual_input.read()

        self.assertEqual(reading.mission_day, 7)

    def test_multiple_measurements_are_preserved(self):
        measurements = (
            MeasurementValue("measurement_a", 10.0, "unit_a"),
            MeasurementValue("measurement_b", 20.0, "unit_b"),
        )

        manual_input = ManualInput(measurements)
        reading = manual_input.read()

        self.assertEqual(reading.measurements, measurements)
        self.assertEqual(len(reading.measurements), 2)


    def test_interactive_input_creates_reading(self):
        answers = iter([
            "3",
            "1",
            "example_measurement",
            "42",
            "example_unit",           
        ])

        manual_input = ManualInput(
            input_function=lambda prompt: next(answers),
            output_function=lambda message: None,  )

        reading = manual_input.read()

        self.assertEqual(reading.mission_day, 3)
        self.assertEqual(len(reading.measurements), 1)            
        self.assertEqual(reading.measurements[0].value, 42.0)


    def test_invalid_number_repeats_only_value(self):
        prompts = []
        messages = []

        answers = iter([
            "",
            "1",
            "example_measurement",
            "not_a_number",
            "nan",
            "42",
            "example_unit",
        ])

        def fake_input(prompt):
            prompts.append(prompt)
            return next(answers)

        manual_input = ManualInput(
            input_function=fake_input,
            output_function=messages.append,
        )

        reading = manual_input.read()

        self.assertEqual(reading.measurements[0].value, 42.0)
        self.assertEqual(prompts.count("Measurement name: "), 1)
        self.assertEqual(
            prompts.count("Enter value for example_measurement: "),
            3,
        )
        self.assertEqual(
            prompts.count("Unit for example_measurement: "),
            1,
        )
        self.assertEqual(
            sum(message.startswith("Error:") for message in messages),
            2,
        )

    def test_empty_measurement_name_is_retried(self):
        prompts = []

        answers = iter([
            "0",
            "1",
            "",
            "example_measurement",
            "10",
            "example_unit",
        ])

        def fake_input(prompt):
            prompts.append(prompt)
            return next(answers)

        manual_input = ManualInput(
            input_function=fake_input,
            output_function=lambda message: None,
        )

        reading = manual_input.read()

        self.assertEqual(reading.mission_day, 0)
        self.assertEqual(prompts.count("Measurement name: "), 2)
        self.assertEqual(
            reading.measurements[0].measurement_type,
            "example_measurement",
        )

    def test_invalid_mission_day_and_count_are_retried(self):
        messages = []

        answers = iter([
            "-1",
            "2",
            "0",
            "1",
            "example_measurement",
            "10",
            "example_unit",
        ])

        manual_input = ManualInput(
            input_function=lambda prompt: next(answers),
            output_function=messages.append,
        )

        reading = manual_input.read()

        self.assertEqual(reading.mission_day, 2)
        self.assertEqual(len(reading.measurements), 1)
        self.assertEqual(
            sum(message.startswith("Error:") for message in messages),
            2,
        )

if __name__ == "__main__":
    unittest.main()



   