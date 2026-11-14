# Made in cooperation with ChatGPT
from types import SimpleNamespace
import unittest

from astro_health.session_assessment import evaluate_session

CONFIG = {'version': 2, 'signals': {
    'heart_rate': {'measurement_type': 'heart_rate', 'unit': 'bpm', 'window': 'instant',
                   'caution_above': 100, 'critical_above': 120},
    'spo2': {'measurement_type': 'spo2', 'unit': '%', 'window': 'instant',
             'caution_below': 95, 'critical_below': 92},
}}


class FakeStore:
    def __init__(self, data):
        self.data = data

    def get_session(self, id):
        return SimpleNamespace(id=id, status='completed',
             started_at='2026-11-14T10:00:00Z', ended_at='2026-11-14T11:00:00Z', reading_count=2)

    def summary(self, id):
        return self.data


class SessionStatusTests(unittest.TestCase):
    def test_recorded_separate_from_good(self):
        heart = SimpleNamespace(measurement_type='heart_rate', value=130, unit='bpm')
        oxygen = SimpleNamespace(measurement_type='spo2', value=97, unit='%')
        result = evaluate_session(FakeStore({'heart_rate': heart, 'spo2': oxygen}),
             4, CONFIG, {'dose_semantics': {}, 'career_history_complete': False})
        results = {x.test_id: x for x in result.tests}
        self.assertTrue(results['heart_rate'].recorded)
        self.assertEqual(results['heart_rate'].status, 'critical')
        self.assertEqual(results['spo2'].status, 'good')
        self.assertFalse(results['blood_pressure'].recorded)
        self.assertEqual(results['blood_pressure'].status, 'missing')
        self.assertEqual(result.session_status, 'completed')
        self.assertLess(result.recorded_tests, result.total_tests)


if __name__ == '__main__':
    unittest.main()
