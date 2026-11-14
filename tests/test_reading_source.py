
# Made in cooperation with ChatGPT
# File: tests/test_reading_source.py

import unittest

from astro_health.models import MeasurementValue, Reading
from astro_health.reading_source import ReadingSource


class TestReadingSource(unittest.TestCase):

    def test_abstract_source_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            ReadingSource()

    def test_subclass_must_implement_read(self):
        class IncompleteSource(ReadingSource):
            pass

        with self.assertRaises(TypeError):
            IncompleteSource()

    def test_concrete_source_can_return_reading(self):
        class ExampleSource(ReadingSource):

            def read(self) -> Reading:
                return Reading(
                    source="example",
                    measurements=(
                        MeasurementValue(
                            measurement_type="test_measurement",
                            value=12.0,
                            unit="test_unit",
                        ),
                    ),
                )

        source = ExampleSource()
        reading = source.read()

        self.assertIsInstance(reading, Reading)
        self.assertEqual(reading.source, "example")
        self.assertEqual(reading.measurements[0].value, 12.0)


if __name__ == "__main__":
    unittest.main()
