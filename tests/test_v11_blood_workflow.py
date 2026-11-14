# Made in cooperation with ChatGPT
"""End-to-end blood JSON import, synthetic simulation and dual-band assessment."""
import json
import tempfile
import unittest
from pathlib import Path

from astro_health.astronaut_assessment import assess_measurement, assess_sex_references, load_rules
from astro_health.blood_tests import (
    FORMAT, load_blood_test, parse_blood_test, save_simulated_blood_test,
    simulate_blood_test,
)
from astro_health.cli import HealthCLI
from astro_health.database import Database
from astro_health.fixed_tests import BLOOD_TEST_FIELDS, MANUAL_TESTS
from astro_health.health_service import HealthService
from astro_health.session_store import SessionStore


class BloodTestWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_rules('config/thresholds.json')

    def test_normal_simulation_all_panels_pass_both_reference_bands(self):
        document = simulate_blood_test(self.config, seed=42)
        self.assertTrue(document['synthetic'])
        self.assertEqual(len(document['measurements']), 12)
        reading = parse_blood_test(document)
        self.assertEqual(reading.source, 'simulated_blood_panel')
        self.assertEqual(len(reading.measurements), 12)
        for measurement in reading.measurements:
            with self.subTest(field=measurement.measurement_type):
                result = assess_measurement(measurement.measurement_type,
                                            measurement.value, measurement.unit, self.config)
                self.assertEqual(result.status, 'good', result.explanation)
                pair = assess_sex_references(measurement.measurement_type,
                                             measurement.value, measurement.unit, self.config)
                self.assertTrue(all(item.status == 'good' for item in pair.values()))

    def test_one_hemoglobin_value_two_independent_ratings(self):
        document = simulate_blood_test(self.config, profile='mixed', seed=3)
        pairs = assess_sex_references('hemoglobin',
                    document['measurements']['hemoglobin']['value'], 'g/dL', self.config)
        self.assertEqual(set(pairs), {'male', 'female'})
        self.assertEqual(pairs['male'].status, 'caution')
        self.assertEqual(pairs['female'].status, 'good')
        self.assertEqual(len([name for name in document['measurements'] if 'hemoglobin' in name]), 1)
        self.assertEqual(assess_measurement('wbc', 10.6, '10^9/L', self.config).status, 'caution')

    def test_blood_fields_are_file_only(self):
        all_manual = {test.test_id for test in MANUAL_TESTS}
        self.assertFalse({field.measurement_type for field in BLOOD_TEST_FIELDS} & all_manual)

    def test_wrong_units_nonfinite_boolean_duplicate_or_unknown_rejected(self):
        start = {'format': FORMAT, 'measurements': {'hemoglobin': {'value': 13.3, 'unit': 'g/dL'}}}
        for case in (
            {'format': FORMAT, 'measurements': {'hemoglobin': {'value': 13.3, 'unit': 'g/L'}}},
            {'format': FORMAT, 'measurements': {'hemoglobin': {'value': -1, 'unit': 'g/dL'}}},
            {'format': FORMAT, 'measurements': {'hemoglobin': {'value': True, 'unit': 'g/dL'}}},
            {'format': FORMAT, 'measurements': {'qtc_interval': {'value': 450, 'unit': 'ms'}}},
            {'format': FORMAT, 'measurements': {}},
            {'format': FORMAT, 'synthetic': 1, 'measurements': start['measurements']},
        ):
            with self.subTest(case=case), self.assertRaises(ValueError):
                parse_blood_test(case)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'dup.json'
            path.write_text('{"format": "' + FORMAT + '", "measurements": {"wbc": '
                            '{"value": 5, "unit": "10^9/L"}, '
                            '"wbc": {"value": 12, "unit": "10^9/L"}}}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
                load_blood_test(path)

    def test_file_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'simulation' / 'blood.json'
            save_simulated_blood_test(path, self.config, seed=6)
            reading = load_blood_test(path)
            self.assertEqual(reading.source, 'simulated_blood_panel')
            self.assertEqual(len(reading.measurements), len(BLOOD_TEST_FIELDS))
            with self.assertRaises(FileExistsError):
                save_simulated_blood_test(path, self.config, seed=6)

    def test_cli_option_11_saves_synthetic_json_and_measurements(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / 'astro_health.db')
            db.initialize()
            inputs = iter(['11', '2', '8'])
            messages = []
            cli = HealthCLI(HealthService(db), input_function=lambda prompt: next(inputs),
                            output_function=messages.append, sensor_realtime=False)
            cli.run()
            saved = db.list_readings()
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].source, 'simulated_blood_panel')
            self.assertEqual(len(saved[0].measurements), 12)
            self.assertEqual(cli.sessions.list_sessions()[0].reading_count, 1)
            files = list((Path(folder) / 'simulations').glob('blood_panel_mixed_*.json'))
            self.assertEqual(len(files), 1)
            self.assertTrue(json.loads(files[0].read_text())['synthetic'])

    def test_cli_option_10_requests_json_and_saves_session_reading(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / 'astro_health.db')
            db.initialize()
            path = Path(folder) / 'blood.json'
            path.write_text(json.dumps({'format': FORMAT, 'measurements': {
                'hemoglobin': {'value': 12.5, 'unit': 'g/dL'},
                'platelets': {'value': 240, 'unit': '10^9/L'},
            }}), encoding='utf-8')
            answers = iter(['10', str(path), 'yes', '8'])
            cli = HealthCLI(HealthService(db), input_function=lambda prompt: next(answers),
                            output_function=lambda m: None, sensor_realtime=False)
            cli.run()
            saved = db.list_readings()
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].source, 'blood_test_json')
            self.assertEqual(len(saved[0].measurements), 2)
            summary = cli.sessions.summary(cli.sessions.list_sessions()[0].id)
            self.assertEqual(summary['hemoglobin'].value, 12.5)


if __name__ == '__main__':
    unittest.main()
