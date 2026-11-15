"""Independent behavior cases for the merged JSON knowledge base."""
import json
import math
import unittest
from pathlib import Path

from ophius.engine import Case, KnowledgeBase, baseline_readings, validate_profile

ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase()

    def findings(self, **kwargs):
        return {f['rule_id']: f for f in self.kb.assess(Case(**kwargs))['findings']}

    def test_missing_is_unknown_not_normal(self):
        result = self.kb.assess(Case())
        self.assertEqual(result['overall'], 'UNKNOWN')
        self.assertEqual(result['findings'], [])

    def test_nonfinite_is_invalid_and_never_normal(self):
        for value in (float('nan'), float('inf'), -float('inf'), True, '72'):
            with self.subTest(value=value):
                result = self.kb.assess(Case(readings={'heart_rate': value}))
                self.assertEqual(result['overall'], 'UNKNOWN')
                self.assertEqual(result['signals'][0]['status'], 'invalid')
                self.assertIsNone(result['signals'][0]['value'])
                json.dumps(result, allow_nan=False)

    def test_negated_missing_measurement_does_not_become_evidence(self):
        expr = {'not': {'signal': 'spo2', 'level': 'caution_below'}}
        self.assertFalse(self.kb.ev(expr, Case()))
        self.assertTrue(self.kb.ev(expr, Case(readings={'spo2': 99})))
        expr2 = {'at_least': {'n': 2, 'of': [
            {'signal': 'spo2', 'level': 'caution_below'},
            {'signal': 'heart_rate', 'level': 'critical_above'}]}}
        self.assertFalse(self.kb.ev(expr2, Case(readings={'spo2': 90})))

    def test_hemoglobin_uses_sex_specific_band(self):
        male = self.findings(sex='male', readings={'hemoglobin': 12.5})
        female = self.findings(sex='female', readings={'hemoglobin': 12.5})
        self.assertIn('B01', male)
        self.assertNotIn('B01', female)
        self.assertTrue(male['B01']['treatments'])
        self.assertEqual(male['B01']['treatment_source'], 'treatment.json')

    def test_leukopenia_fever_escalates_from_real_combination(self):
        plain = self.findings(readings={'wbc': 2})
        fever = self.findings(readings={'wbc': 2, 'core_temperature': 38})
        self.assertEqual(plain['B03']['level'], 'SUSPECTED')
        self.assertEqual(fever['B03']['level'], 'EMERGENCY')

    def test_both_treatment_identifier_styles_resolve(self):
        allergy = self.findings(symptoms={'pruritus'}, context={'suspected_allergen_exposure'})
        low_platelets = self.findings(readings={'platelets': 100})
        self.assertTrue(allergy['C01']['treatments'])
        self.assertTrue(low_platelets['B05']['treatments'])
        self.assertEqual(allergy['C01']['steps'], [])
        # Warnings remain diagnostic information, not superseded old treatment.
        self.assertTrue(allergy['C01']['do_not'])

    def test_red_flag_hides_benign_treatment(self):
        # Fever alongside adaptation congestion must not show benign therapy.
        rule = self.kb.rules_by_id['C07']
        case = Case(symptoms={'nasal_congestion'}, context={'recent_microgravity_transition'},
                    readings={'core_temperature': 38})
        result = self.kb.evaluate_rule(rule, case)
        self.assertTrue(result['red_flag'])
        finding = self.kb.build_finding(result, case)
        self.assertEqual(finding['treatments'], [])
        self.assertTrue(finding['hide_therapy'])

    def test_qtc_link_appears_at_sex_threshold_and_has_critical_level(self):
        self.assertNotIn('QTC', self.findings(sex='male', readings={'qtc_interval': 450}))
        self.assertIn('QTC', self.findings(sex='male', readings={'qtc_interval': 451}))
        self.assertNotIn('QTC', self.findings(sex='female', readings={'qtc_interval': 451}))
        result = self.findings(sex='female', readings={'qtc_interval': 501})['QTC']
        self.assertEqual(result['level'], 'URGENT')
        self.assertEqual(result['treatments'], self.kb.treatment_for('qtc_interval_prolongation'))

    def test_missing_electrolyte_limits_do_not_create_detectors(self):
        findings = self.findings(readings={'potassium': 1, 'magnesium': 0.1})
        self.assertFalse(findings)
        self.assertTrue(self.kb.treatment_for('hypokalemia'))

    def test_threshold_boundaries_and_mission_scaling_are_shared(self):
        case = Case(readings={'heart_rate': 110}, mission_duration_days=730)
        self.assertEqual(self.kb.assess(case)['signals'][0]['status'], 'critical')
        self.assertEqual(self.kb.limits_for('nuclear_source_dose', case)['critical_above'], 40)

    def test_english_metadata_and_rule_count(self):
        metadata = self.kb.meta()
        self.assertEqual(len(metadata['rules']), 38)
        self.assertEqual(len(metadata['treatment_library']), 42)
        self.assertIn('Hematological', metadata['rule_groups'])


class BaselineTests(unittest.TestCase):
    def test_profiles_are_independent_documents(self):
        a = json.loads((ROOT / 'profiles' / 'A-101.json').read_text())
        b = json.loads((ROOT / 'profiles' / 'A-102.json').read_text())
        copy = validate_profile(a)
        self.assertEqual(copy, a)
        copy['personal_information']['age'] = 99
        self.assertEqual(a['personal_information']['age'], 38)
        fa, fb = baseline_readings(a), baseline_readings(b)
        self.assertEqual(fa['cumulative_effective_dose']['value'], 120)
        self.assertEqual(fb['cumulative_effective_dose']['value'], 145)
        self.assertEqual(fb['qtc_interval']['value'], 430)
        self.assertEqual(fa['heart_rate']['timestamp'], '2025-08-11T09:30:00Z')
        self.assertNotIn('skin_temperature', fa)

    def test_invalid_profile_rejected(self):
        original = json.loads((ROOT / 'profiles' / 'A-101.json').read_text())
        for bad in (0, -1, True, 1.5):
            profile = json.loads(json.dumps(original))
            profile['mission_details']['duration_days'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_profile(profile)
        original['pre_flight_baseline']['blood_tests']['cbc']['wbc']['value'] = float('nan')
        with self.assertRaises(ValueError):
            validate_profile(original)


if __name__ == '__main__':
    unittest.main()
