# Made in cooperation with ChatGPT
"""V14: all JSON sensor outputs must surface in ordinary sessions."""
import tempfile
import unittest
from pathlib import Path

from astro_health.astronaut_assessment import load_rules, load_settings
from astro_health.cli import HealthCLI
from astro_health.database import Database
from astro_health.health_service import HealthService
from astro_health.json_session_view import evaluate_json_session
from astro_health.sensor_packets import SensorPacket
from astro_health.sensor_processing import ProcessingError, process_packet
from astro_health.sensor_simulators import make_simulated_packet


class JsonSensorCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db = Database(Path(self.temp.name) / 'test.sqlite3')
        db.initialize()
        self.lines = []
        self.app = HealthCLI(HealthService(db), output_function=self.lines.append, json_only=True,
                             sensor_realtime=False)
        self.app.sessions.initialize()
        self.app.current_session_id = self.app.sessions.start()
        self.rules = load_rules(Path(__file__).resolve().parents[1] / 'config' / 'thresholds.json')
        self.settings = load_settings(None)

    def tearDown(self):
        self.temp.cleanup()

    def view(self):
        return evaluate_json_session(self.app.sessions, self.app.current_session_id, self.rules, self.settings)

    def test_empty_session_has_exact_json_names_not_legacy_test_fields(self):
        rows = self.view().tests
        names = {r.test_id for r in rows}
        self.assertEqual(set(self.rules['signals']), names - {r['condition_id'] for r in self.rules['condition_cutoffs']})
        self.assertTrue(all(r.status == 'missing' for r in rows))
        self.assertNotIn('hrv_rmssd', names)
        self.assertNotIn('co2_concentration', names)

    def test_all_sensor_simulators_populate_their_json_measurements(self):
        sensors = ('thermistor', 'ppg', 'ecg', 'blood_pressure', 'co2', 'lab_analyzer', 'radiation')
        for sensor in sensors:
            self.app._record_packets((make_simulated_packet(sensor),), ingest_channel='simulation')
        results = {r.test_id: r for r in self.view().tests}
        for key in ('heart_rate', 'spo2', 'skin_temperature', 'blood_pressure_systolic',
                    'blood_pressure_diastolic', 'qtc_interval_male', 'qtc_interval_female',
                    'cabin_co2', 'hemoglobin_male', 'hemoglobin_female', 'platelets'):
            self.assertIn(results[key].status, ('good', 'caution', 'critical'), key)
        self.assertEqual(results['lens_dose_30d'].status, 'missing')

    def test_reported_doses_need_provenance_not_an_instant_packet(self):
        for i in range(4):
            self.app._record_packets((make_simulated_packet('dose_report', i),), ingest_channel='simulation')
        results = {r.test_id: r for r in self.view().tests}
        for key, rule in self.rules['signals'].items():
            if rule.get('category') == 'radiation':
                self.assertEqual(results[key].status, 'unassessed', key)
                self.assertTrue(results[key].recorded)
        self.assertEqual(results['vomiting_episodes'].status, 'missing')

    def test_dose_report_correct_coverage_assessed(self):
        raw = make_simulated_packet('dose_report', 0).to_dict()
        raw['data']['coverage_start'] = '2026-10-01'
        raw['data']['coverage_end'] = '2026-10-30'
        self.app._record_packets((SensorPacket.from_dict(raw),), ingest_channel='simulation')
        results = {r.test_id: r for r in self.view().tests}
        self.assertEqual(results['lens_dose_30d'].status, 'good')
        self.assertEqual(results['lens_dose_1y'].status, 'missing')

    def test_option_four_all_sensors_fills_dose_names_not_symptoms(self):
        self.app.input_function = lambda _prompt: '0'
        self.app._simulate_sensor()
        result = {r.test_id: r for r in self.view().tests}
        self.assertEqual(len(result), len(self.rules['signals']) + len(self.rules['condition_cutoffs']))
        for key, rule in self.rules['signals'].items():
            if rule.get('category') == 'radiation':
                self.assertEqual(result[key].status, 'unassessed', key)
            elif key != 'vomiting_episodes':
                self.assertIn(result[key].status, ('good', 'caution', 'critical'), key)
        self.assertEqual(result['vomiting_episodes'].status, 'missing')

    def test_bad_dosimetry_names_and_units_cannot_be_invented(self):
        raw = make_simulated_packet('dose_report', 0).to_dict()
        raw['data']['made_up_radiation_reading'] = 123.0
        with self.assertRaises(ProcessingError):
            process_packet(SensorPacket.from_dict(raw))
        self.assertEqual(self.rules['signals']['blood_pressure_systolic']['unit'], 'mmHg')


if __name__ == '__main__':
    unittest.main()
