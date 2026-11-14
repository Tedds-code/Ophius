# Made in cooperation with ChatGPT
"""Contract checks: simulate and assess every source JSON rule, no made-up windows."""
import json
import tempfile
import unittest
from pathlib import Path

from astro_health.astronaut_assessment import load_rules
from astro_health.database import Database
from astro_health.health_service import HealthService
from astro_health.cli import HealthCLI
from astro_health.json_catalog_simulation import (
    save_simulation, load_simulation, simulate_catalog,
)
from astro_health.sensor_simulators import make_simulated_packet
from astro_health.sensor_processing import process_packet
from astro_health.session_store import SessionStore
from astro_health.session_assessment import evaluate_session


CONFIG = load_rules('config/thresholds.json')


class JsonFirstTests(unittest.TestCase):
    def test_all_44_json_rules_and_conditions_have_synthetic_assessments(self):
        data = simulate_catalog(CONFIG)
        self.assertEqual(set(data['assessments']), set(CONFIG['signals']))
        self.assertEqual(set(data['condition_assessments']),
                         {r['condition_id'] for r in CONFIG['condition_cutoffs']})
        self.assertEqual(len(data['daily_history']), 365)
        self.assertTrue(all(r['synthetic'] for r in data['daily_history']))
        self.assertTrue(all(v['status'] == 'good' for v in data['assessments'].values()))
        self.assertEqual(data['condition_assessments']['back_pain_space_adaptation']['status'], 'context_only')

    def test_mixed_reference_sex_difference_and_real_critical(self):
        data = simulate_catalog(CONFIG, profile='mixed')
        self.assertEqual(data['assessments']['hemoglobin_male']['value'],
                         data['assessments']['hemoglobin_female']['value'])
        self.assertEqual(data['assessments']['hemoglobin_male']['status'], 'caution')
        self.assertEqual(data['assessments']['hemoglobin_female']['status'], 'good')
        self.assertEqual(data['assessments']['blood_pressure_systolic']['status'], 'critical')

    def test_file_validates_dates_history_coverage_and_derived_dose(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            save_simulation(path, CONFIG, profile='mixed')
            data = load_simulation(path, CONFIG)
            self.assertEqual(len(data['daily_history']), 365)
            data['daily_history'][5]['date'] = data['daily_history'][4]['date']
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'missing or duplicate dates'):
                load_simulation(path, CONFIG)
            save_simulation(Path(tmp) / 'good.json', CONFIG)
            good = Path(tmp) / 'good.json'
            data = json.loads(good.read_text())
            data['assessments']['lens_dose_30d']['value'] = 0
            good.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'does not match daily history'):
                load_simulation(good, CONFIG)

    def test_cuff_and_ppg_and_ecg_report_json_measurements(self):
        expected = {
            'blood_pressure': ('blood_pressure_systolic', 'blood_pressure_diastolic'),
            'ppg': ('heart_rate', 'spo2'),
            'ecg': ('qtc_interval',),
            'co2': ('cabin_co2',),
            'thermistor': ('skin_temperature',),
        }
        for sensor, names in expected.items():
            with self.subTest(sensor=sensor):
                packet = make_simulated_packet(sensor)
                result = process_packet(packet)
                measured = {m.measurement_type for m in result.reading.measurements}
                self.assertTrue(set(names).issubset(measured))

    def test_regular_cli_launch_records_all_json_assessments(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / 'astro.db')
            database.initialize()
            service = HealthService(database)
            lines = []
            entries = iter(('8',))
            cli = HealthCLI(service, input_function=lambda _: next(entries),
                            output_function=lines.append, sensor_realtime=False,
                            auto_full_simulation=True, json_only=True)
            cli.run()
            store = SessionStore(database)
            session = store.list_sessions()[0]
            view = evaluate_session(store, session.id, CONFIG, {})
            self.assertEqual(view.total_tests, 50)
            self.assertEqual(view.recorded_tests, 50)
            self.assertEqual({r.test_id for r in view.tests[:44]}, set(CONFIG['signals']))
            self.assertFalse(any(r.status in ('unassessed', 'missing') for r in view.tests))
            self.assertTrue(any('SYNTHETIC' in r.display_value for r in view.tests))
            self.assertTrue((Path(tmp) / 'simulations' / 'session_reports.json').exists())
            report = json.loads((Path(tmp) / 'simulations' / 'session_reports.json').read_text())
            load_simulation(report[str(session.id)], CONFIG)


if __name__ == '__main__':
    unittest.main()
