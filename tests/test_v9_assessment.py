# Made in cooperation with ChatGPT
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from astro_health.astronaut_assessment import (
    assess_measurement, load_rules, load_settings, rule_name,
)


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.config = {'version': 2, 'signals': {
            'heart_rate': {'measurement_type': 'heart_rate', 'unit': 'bpm',
                'window': 'instant', 'caution_below': 50, 'caution_above': 100,
                'critical_below': 40, 'critical_above': 120,
                'enabled_for_comparison': True},
            'skin_temperature': {'measurement_type': 'skin_temperature', 'unit': 'degC',
                'window': 'instant', 'caution_below': 35.5, 'caution_above': 37.3,
                'critical_below': 34, 'critical_above': 38,
                'enabled_for_comparison': False},
            'lens_dose_30d': {'measurement_type': 'lens_dose', 'unit': 'mGy-Eq',
                'window': '30_days', 'critical_above': 1000},
            'lens_dose_career': {'measurement_type': 'lens_dose', 'unit': 'mGy-Eq',
                'window': 'career', 'critical_above': 4000},
            'career': {'measurement_type': 'career_effective_dose', 'unit': 'mSv',
                'window': 'career', 'critical_above': 600},
            'co2': {'measurement_type': 'co2_concentration', 'unit': 'ppm',
                'window': 'instant', 'caution_above': 20000,
                'enabled_for_comparison': False},
        }}

    def test_heart_rate_levels(self):
        for x, status in [(70, 'good'), (101, 'caution'), (121, 'critical'),
                          (39, 'critical'), (40, 'caution'), (100, 'good')]:
            self.assertEqual(assess_measurement('heart_rate', x, 'bpm', self.config).status, status)

    def test_project_reference_used_even_if_unverified_or_disabled_in_old_overlay(self):
        self.assertEqual(assess_measurement('skin_temperature', 39, 'degC', self.config).status, 'critical')
        self.assertEqual(assess_measurement('co2_concentration', 20001, 'ppm', self.config).status, 'caution')

    def test_missing_and_unassessed_never_green(self):
        self.assertEqual(assess_measurement('heart_rate', None, 'bpm', self.config).status, 'missing')
        self.assertEqual(assess_measurement('unlisted', 12, 'ohm', self.config).status, 'unassessed')
        self.assertEqual(assess_measurement('heart_rate', 70, 'bpm', self.config, quality='suspect').status, 'unassessed')

    def test_dose_requires_coverage(self):
        self.assertEqual(assess_measurement('career_effective_dose', 650, 'mSv', self.config).status, 'unassessed')
        self.assertEqual(assess_measurement('career_effective_dose', 650, 'mSv', self.config,
                            career_history_complete=True).status, 'critical')
        self.assertEqual(assess_measurement('lens_dose', 1400, 'mGy-Eq', self.config).status, 'unassessed')
        self.assertEqual(assess_measurement('lens_dose', 1400, 'mGy-Eq', self.config,
                            window_values={'30_days': 1001}).status, 'critical')
        self.assertEqual(assess_measurement('gcr_effective_dose_rate', 3, 'mSv/day', self.config).status, 'unassessed')

    def test_original_v1_units(self):
        v1 = {'version': 1, 'signals': {
            'cabin_co2': {'unit': '%', 'window': 'instant', 'caution_above': 2.0},
            'skin_temperature': {'unit': 'C', 'window': 'instant', 'critical_above': 38},
            'lens_dose_30d': {'unit': 'mGy-Eq', 'window': '30_days', 'critical_above': 1000}}}
        self.assertEqual(assess_measurement('co2_concentration', 22000, 'ppm', v1).status, 'caution')
        self.assertEqual(assess_measurement('skin_temperature', 39, 'degC', v1).status, 'critical')
        self.assertEqual(rule_name('lens_dose_30d', v1['signals']['lens_dose_30d']), 'lens_dose')

    def test_settings_optin_defaults_and_validation(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'settings.json'
            self.assertFalse(load_settings(p)['career_history_complete'])
            p.write_text(json.dumps({'mission_days': -2}))
            with self.assertRaises(ValueError):
                load_settings(p)
            p.write_text(json.dumps({'mission_days': 80, 'career_history_complete': True,
                                     'dose_semantics': {'lens_dose': {'mode': 'cumulative', 'verified': True}}}))
            self.assertEqual(load_settings(p)['mission_days'], 80)


if __name__ == '__main__':
    unittest.main()
