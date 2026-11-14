# Made in cooperation with ChatGPT
"""Dashboard labels distinguish a missing reading from a completed comparison."""
import unittest
from astro_health.dashboard import assessment_display_state
from astro_health.session_assessment import TestResult


class AssessmentLabelTests(unittest.TestCase):
    def row(self, recorded, status):
        return TestResult('Example', 'example', recorded, status, '—', '')

    def test_no_reading(self):
        self.assertEqual(assessment_display_state(self.row(False, 'missing')), 'NOT MEASURED')

    def test_compared_readings(self):
        for status in ('good', 'caution', 'critical'):
            with self.subTest(status=status):
                self.assertEqual(assessment_display_state(self.row(True, status)), 'ASSESSED')

    def test_reading_without_sufficient_context(self):
        self.assertEqual(assessment_display_state(self.row(True, 'unassessed')), 'NEEDS CONTEXT')
