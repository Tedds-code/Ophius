# Made in cooperation with ChatGPT
# File: tests/test_fixed_manual_input.py

import unittest

from astro_health.fixed_manual_input import FixedManualInput
from astro_health.fixed_tests import FIXED_TESTS


class TestFixedManualInput(unittest.TestCase):

    def make_source(self, responses):
        answers = iter(responses)
        messages = []
        source = FixedManualInput(
            input_function=lambda prompt: next(answers),
            output_function=messages.append,
        )
        return source, messages

    def test_catalog_contains_unique_identifiers(self):
        ids = [test.test_id for test in FIXED_TESTS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_single_value_has_fixed_type_and_unit(self):
        source, _ = self.make_source(["", "1", "32.5"])
        reading = source.read()
        self.assertEqual(reading.measurements[0].measurement_type, "skin_temperature")
        self.assertEqual(reading.measurements[0].unit, "degC")
        self.assertEqual(reading.measurements[0].value, 32.5)

    def test_blood_pressure_is_two_values(self):
        source, _ = self.make_source(["3", "5", "120", "80"])
        reading = source.read()
        self.assertEqual(reading.mission_day, 3)
        self.assertEqual(
            [m.measurement_type for m in reading.measurements],
            ["systolic_pressure", "diastolic_pressure"],
        )
        self.assertEqual(
            [m.unit for m in reading.measurements],
            ["mmHg", "mmHg"],
        )

    def test_invalid_selection_reprompts(self):
        source, messages = self.make_source(["", "999", "1", "31"])
        source.read()
        self.assertTrue(any("Invalid test number" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
