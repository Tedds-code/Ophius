# Made in cooperation with ChatGPT
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from astro_health.radiation_intervals import load_intervals, summarize_intervals
from astro_health.radiation_trends import analyze_history

UTC = timezone.utc
ASOF = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
CONFIG = {'version': 2, 'signals': {
    'lens_dose_career': {'measurement_type': 'lens_dose', 'unit': 'mGy-Eq',
                         'window': 'career', 'critical_above': 4000},
    'lens_dose_30d': {'measurement_type': 'lens_dose', 'unit': 'mGy-Eq',
                      'window': '30_days', 'critical_above': 1000},
}}


def reading(id, date, value, *, field='lens_dose', source='sensor-a', quality='unassessed'):
    return SimpleNamespace(id=id, timestamp=date, source=source, quality=quality,
       measurements=[SimpleNamespace(measurement_type=field, value=value, unit='mGy-Eq')])


class RadiationTests(unittest.TestCase):
    def test_defaults_no_counter_assumption(self):
        readings = [reading(1, ASOF - timedelta(days=30), 10), reading(2, ASOF, 50)]
        output = analyze_history(readings, CONFIG, {'career_history_complete': False,
            'dose_semantics': {}}, as_of=ASOF)['lens_dose']
        self.assertIsNone(output.forecast_days_to_limit)
        self.assertEqual(output.windows, {})
        self.assertIsNone(output.observed_delta)

    def test_exact_window_and_linear_forecast(self):
        samples = [reading(1, ASOF-timedelta(days=30), 100),
                   reading(2, ASOF-timedelta(days=20), 120),
                   reading(3, ASOF-timedelta(days=10), 140),
                   reading(4, ASOF, 160)]
        output = analyze_history(samples, CONFIG, {'career_history_complete': True,
            'dose_semantics': {'lens_dose': {'mode': 'cumulative', 'verified': True}}}, as_of=ASOF)['lens_dose']
        self.assertEqual(output.windows['30_days'], 60)
        self.assertEqual(output.career, 160)
        self.assertEqual(output.observed_delta, 60)
        self.assertAlmostEqual(output.daily_change_estimate, 2)
        self.assertAlmostEqual(output.forecast_days_to_limit, 1920)

    def test_no_source_mixing_or_counter_resets(self):
        samples = [reading(1, ASOF-timedelta(days=30), 110, source='A'),
                   reading(2, ASOF-timedelta(days=15), 120, source='A'),
                   reading(3, ASOF, 20, source='B')]
        output = analyze_history(samples, CONFIG, {'career_history_complete': True,
            'dose_semantics': {'lens_dose': {'mode': 'cumulative', 'verified': True}}}, as_of=ASOF)['lens_dose']
        self.assertIsNone(output.observed_delta)
        self.assertEqual(output.windows, {})
        self.assertTrue(any('Multiple dose sources' in n for n in output.notes))

    def test_invalid_qualities_not_used(self):
        samples = [reading(1, ASOF-timedelta(days=30), 100),
                   reading(2, ASOF, 9000, quality='suspect')]
        output = analyze_history(samples, CONFIG, {'career_history_complete': True,
            'dose_semantics': {'lens_dose': {'mode': 'cumulative', 'verified': True}}}, as_of=ASOF)['lens_dose']
        self.assertEqual(output.latest, 100)

    def test_interval_contiguity(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'radiation.jsonl'
            start = ASOF - timedelta(days=30)
            rows = []
            for day in range(30):
                a = start + timedelta(days=day)
                b = a + timedelta(days=1)
                rows.append('{' + f'"measurement_type":"lens_dose","unit":"mGy-Eq","dose_increment":1,'
                            f'"start":"{a.isoformat()}","end":"{b.isoformat()}",'
                            '"source_id":"dosimeter","verified":true}' )
            p.write_text('\n'.join(rows) + '\n', encoding='utf-8')
            records = load_intervals(p)['lens_dose']
            windows, life, days = summarize_intervals(records, ASOF)
            self.assertEqual(windows['30_days'], 30)
            self.assertEqual(life, 30)
            self.assertEqual(days, 30)
            # A gap prevents claiming the full 30-day dose.
            gap_records = records[:15] + records[16:]
            windows, life, days = summarize_intervals(gap_records, ASOF)
            self.assertNotIn('30_days', windows)
            self.assertIsNone(life)

    def test_interval_overlap_rejected(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'radiation.jsonl'
            p.write_text('\n'.join([
                '{"measurement_type":"lens_dose","unit":"mGy-Eq","dose_increment":5,"start":"2026-11-01T00:00:00Z","end":"2026-11-03T00:00:00Z","source_id":"a","verified":true}',
                '{"measurement_type":"lens_dose","unit":"mGy-Eq","dose_increment":5,"start":"2026-11-02T00:00:00Z","end":"2026-11-04T00:00:00Z","source_id":"a","verified":true}',
            ]))
            with self.assertRaisesRegex(ValueError, 'Overlapping'):
                load_intervals(p)


if __name__ == '__main__':
    unittest.main()
