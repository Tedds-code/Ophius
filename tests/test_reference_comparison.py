# Made in cooperation with ChatGPT
# File: tests/test_reference_comparison.py

import json
import tempfile
import unittest
from pathlib import Path

from astro_health.models import MeasurementValue, Reading
from astro_health.reference_comparison import (
    ReferenceError, compare_reading, load_reference_rules,
)


class TestReferenceComparison(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "rules.json"

    def save(self, rules):
        self.file.write_text(json.dumps({"schema_version": 1, "rules": rules}))
        return load_reference_rules(self.file)

    def test_empty_rules_do_not_make_medical_judgments(self):
        rules = self.save([])
        reading = Reading("simulated_co2", (MeasurementValue("co2_concentration", 600, "ppm"),))
        results = compare_reading(reading, rules)
        self.assertEqual(results[0].status, "no_reference")
        self.assertEqual(reading.quality, "unassessed")

    def test_synthetic_arithmetic_comparison(self):
        # Fictional bounds test ONLY the comparator's arithmetic.
        rules = self.save([{
            "measurement_type": "co2_concentration", "unit": "ppm",
            "lower": 3, "upper": 7,
            "source": "fictional unit-test example", "context": "test arithmetic only",
        }])
        reading = Reading("manual", (MeasurementValue("co2_concentration", 8, "ppm"),))
        result = compare_reading(reading, rules)[0]
        self.assertEqual(result.status, "outside_reference_range")
        self.assertEqual(reading.quality, "unassessed")

    def test_reject_mismatched_units(self):
        with self.assertRaises(ReferenceError):
            self.save([{
                "measurement_type": "co2_concentration", "unit": "degC",
                "lower": 0, "upper": 10,
                "source": "fictional", "context": "test",
            }])

    def test_reject_missing_provenance(self):
        with self.assertRaises(ReferenceError):
            self.save([{
                "measurement_type": "co2_concentration", "unit": "ppm",
                "lower": 0, "upper": 10,
            }])

    def test_reject_invalid_bounds(self):
        with self.assertRaises(ReferenceError):
            self.save([{
                "measurement_type": "co2_concentration", "unit": "ppm",
                "lower": 10, "upper": 0,
                "source": "fictional", "context": "test",
            }])


if __name__ == "__main__":
    unittest.main()
