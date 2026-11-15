from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from astrohealth.monitor import Monitor

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
        self.monitor = Monitor(Path(self.temp.name), ROOT/'config', ROOT/'profiles', clock=lambda: self.now)
        self.counter = 0

    def tearDown(self):
        self.monitor.close()
        self.temp.cleanup()

    def packet(self, readings=None, **extra):
        self.counter += 1
        return {'packet_id': str(self.counter), 'timestamp': self.now.isoformat(), 'source': 'simulation',
                'readings': readings or {'heart_rate': {'value': 72, 'unit': 'bpm'}}, **extra}

    def row(self, snap, key):
        return next(row for row in snap['readings'] if row['key'] == key)

    def test_profile_baselines_never_seed_current_readings(self):
        snap = self.monitor.snapshot('A-101')
        self.assertIsNone(snap['mission_day'])
        self.assertEqual(snap['assessment']['overall'], 'UNKNOWN')
        row = self.row(snap, 'heart_rate')
        self.assertIsNone(row['value'])
        self.assertEqual(row['baseline']['value'], 62)

    def test_immediate_limit_warning_and_sixty_second_expiry(self):
        snap = self.monitor.ingest('A-101', self.packet({'spo2': {'value': 89, 'unit': '%'}}))
        self.assertEqual(self.row(snap, 'spo2')['status'], 'critical')
        self.assertTrue(snap['alerts'])
        self.now += timedelta(seconds=61)
        self.monitor.tick()
        snap = self.monitor.snapshot('A-101')
        self.assertEqual(self.row(snap, 'spo2')['status'], 'stale')
        self.assertIsNone(self.row(snap, 'spo2')['value'])
        self.assertEqual(snap['monitoring']['buffer_samples'], 0)
        self.assertTrue(snap['alerts'])

    def test_bad_packet_validation_is_atomic(self):
        self.monitor.ingest('A-101', self.packet())
        self.now += timedelta(seconds=1)
        with self.assertRaises(ValueError):
            self.monitor.ingest('A-101', self.packet({'heart_rate': {'value': 200, 'unit': 'bpm'},
                'spo2': {'value': 'bad', 'unit': '%'}}))
        self.assertEqual(self.row(self.monitor.snapshot('A-101'), 'heart_rate')['value'], 72)
        self.assertEqual(self.monitor.history('A-101')['events'], [])

    def test_nonfinite_wrong_units_old_and_duplicate_rejected(self):
        p = self.packet()
        self.monitor.ingest('A-101', p)
        with self.assertRaises(ValueError): self.monitor.ingest('A-101', p)
        for value, unit in [(float('nan'), 'bpm'), (float('inf'), 'bpm'), (True, 'bpm'), (71, 'Hz')]:
            with self.assertRaises(ValueError):
                self.monitor.ingest('A-101', self.packet({'heart_rate': {'value': value, 'unit': unit}}))
        with self.assertRaises(ValueError): self.monitor.ingest('A-101', self.packet())

    def test_cardiac_sequence_within_buffer_and_disconnection_separate(self):
        self.monitor.ingest('A-101', self.packet())
        self.now += timedelta(seconds=2)
        self.monitor.ingest('A-101', self.packet({'heart_rate': {'value': 155, 'unit': 'bpm'}}))
        self.now += timedelta(seconds=2)
        snap = self.monitor.ingest('A-101', self.packet({'heart_rate': {'value': 0, 'unit': 'bpm'}}))
        event = next(a for a in snap['alerts'] if a['kind'] == 'possible_cardiac_arrest')
        self.assertTrue(event['sequence_within_buffer'])
        self.assertEqual(snap['assessment']['overall'], 'EMERGENCY')
        self.assertTrue(event['treatments'])
        self.now += timedelta(seconds=2)
        snap2 = self.monitor.ingest('A-102', self.packet({'heart_rate': {'value': 0, 'unit': 'bpm'}}, quality='disconnected'))
        self.assertEqual(snap2['assessment']['overall'], 'UNKNOWN')
        self.assertEqual(snap2['alerts'][0]['kind'], 'sensor_fault')
        self.assertIsNone(snap2['mission_day'])

    def test_daily_aggregates_persist_without_normal_raw_and_restart_merge(self):
        self.monitor.ingest('A-101', self.packet())
        self.now += timedelta(seconds=10)
        self.monitor.ingest('A-101', self.packet({'heart_rate': {'value': 78, 'unit': 'bpm'}}))
        self.monitor.close()
        self.monitor = Monitor(Path(self.temp.name), ROOT/'config', ROOT/'profiles', clock=lambda: self.now)
        history = self.monitor.history('A-101')
        row = history['daily'][0]
        self.assertEqual(row['mean'], 75)
        self.assertEqual(row['time_weighted_mean'], 72)
        self.assertEqual(row['coverage_seconds'], 10)
        self.assertIsNone(self.row(self.monitor.snapshot('A-101'), 'heart_rate')['value'])
        self.now += timedelta(seconds=10)
        self.monitor.ingest('A-101', self.packet({'heart_rate': {'value': 75, 'unit': 'bpm'}}))
        row = self.monitor.history('A-101')['daily'][0]
        self.assertEqual(row['count'], 3)
        self.assertEqual(row['mean'], 75)
        tables = [row[0] for row in self.monitor.storage.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertNotIn('readings', tables)
        self.assertNotIn('raw_samples', tables)

    def test_mission_calendar_days_and_separate_synthetic_epoch(self):
        self.monitor.ingest('A-101', self.packet())
        self.now += timedelta(days=5)
        self.assertEqual(self.monitor.snapshot('A-101')['mission_day'], 6)
        snap = self.monitor.ingest('A-101', self.packet(source='jsonl'))
        self.assertEqual(snap['mission_day'], 1)
        self.assertEqual(snap['active_source'], 'observed')
        self.assertEqual(snap['alerts'], [])

    def test_laboratory_persistence_and_unsupported_electrolytes_ignored(self):
        snap = self.monitor.import_lab('A-101', {'report_id': 'lab1', 'timestamp': self.now.isoformat(),
            'synthetic': True, 'measurements': {'hemoglobin': {'value': 11, 'unit': 'g/dL'},
                'potassium': {'value': 1, 'unit': 'mEq/L'}}})
        self.assertIn('potassium', snap['import']['ignored_measurements'])
        self.assertTrue(any(f['rule_id'] == 'B01' for f in snap['assessment']['findings']))
        self.now += timedelta(minutes=2)
        snap = self.monitor.snapshot('A-101')
        self.assertEqual(self.row(snap, 'hemoglobin')['value'], 11)
        self.assertEqual(self.row(snap, 'hemoglobin')['type'], 'lab')
        with self.assertRaises(ValueError):
            self.monitor.import_lab('A-101', {'report_id': 'lab1','timestamp': self.now.isoformat(),
                'measurements': {'hemoglobin': {'value': 15, 'unit': 'g/dL'}}})

    def test_co2_and_dose_require_coverage_and_do_not_imply_normal(self):
        snap = self.monitor.ingest('A-101', self.packet({'cabin_co2': {'value': 2, 'unit': 'mmHg'},
            'lens_dose_30d': {'value': 10, 'unit': 'mGy-Eq'}}))
        self.assertEqual(self.row(snap, 'cabin_co2')['status'], 'needs_context')
        self.assertEqual(self.row(snap, 'lens_dose_30d')['status'], 'needs_context')
        self.assertEqual(snap['assessment']['overall'], 'UNKNOWN')

    def test_verified_mission_report_forecast_is_conditional_not_alarm(self):
        start = self.now - timedelta(days=10)
        self.monitor.ingest('A-101', self.packet({'nuclear_source_dose': {'value': 35, 'unit': 'mSv',
            'metadata': {'kind': 'cumulative', 'verified': True, 'window': 'per_mission_year',
                'coverage_start': start.isoformat(), 'coverage_end': self.now.isoformat()}}}))
        self.now += timedelta(seconds=61)
        snap = self.monitor.snapshot('A-101')
        self.assertEqual(self.row(snap, 'nuclear_source_dose')['value'], 35)
        self.assertEqual(self.row(snap, 'nuclear_source_dose')['type'], 'accumulated')
        before = len(snap['alerts'])
        forecast = self.monitor.forecast('A-101', {'key': 'nuclear_source_dose', 'unit': 'mSv', 'daily_rate': 1, 'horizon_days': 21})
        self.assertEqual(forecast['threshold'], 40)
        self.assertEqual(forecast['days_to_threshold'], 5)
        self.assertTrue(forecast['crosses_within_horizon'])
        self.assertEqual(len(self.monitor.snapshot('A-101')['alerts']), before)

    def test_cumulative_counters_not_summed_and_reset_needs_context(self):
        start = self.now - timedelta(days=1)
        def dose(value):
            return {'nuclear_source_dose': {'value': value, 'unit': 'mSv', 'metadata': {'kind': 'cumulative',
                'verified': True, 'window': 'per_mission_year', 'coverage_start': start.isoformat(), 'coverage_end': self.now.isoformat()}}}
        self.monitor.ingest('A-101', self.packet(dose(5)))
        self.now += timedelta(seconds=2)
        self.monitor.ingest('A-101', self.packet(dose(6)))
        self.assertEqual(self.monitor.forecast('A-101', {'key':'nuclear_source_dose','unit':'mSv','daily_rate':1})['current_total'],6)
        self.now += timedelta(seconds=2)
        self.monitor.ingest('A-101', self.packet(dose(1)))
        self.assertEqual(self.monitor.forecast('A-101', {'key':'nuclear_source_dose','unit':'mSv','daily_rate':1})['status'],'insufficient_data')

    def test_acknowledgement_does_not_repeat_same_episode(self):
        snap = self.monitor.ingest('A-101', self.packet({'spo2': {'value': 89, 'unit': '%'}}))
        event = next(a for a in snap['alerts'] if a['kind'] == 'threshold')
        self.monitor.acknowledge('A-101', event['id'])
        self.now += timedelta(seconds=2)
        snap = self.monitor.ingest('A-101', self.packet({'spo2': {'value': 89, 'unit': '%'}}))
        self.assertFalse(any(a['kind'] == 'threshold' for a in snap['alerts']))
        self.now += timedelta(seconds=2)
        self.monitor.ingest('A-101', self.packet({'spo2': {'value': 98, 'unit': '%'}}))
        self.now += timedelta(seconds=2)
        snap = self.monitor.ingest('A-101', self.packet({'spo2': {'value': 89, 'unit': '%'}}))
        self.assertTrue(any(a['kind'] == 'threshold' for a in snap['alerts']))

    def test_mission_coverage_and_future_co2_context_rejected(self):
        self.monitor.ingest('A-101', self.packet())
        start = self.now
        self.now += timedelta(days=10)
        snap = self.monitor.ingest('A-101', self.packet({'nuclear_source_dose': {'value': 1, 'unit': 'mSv',
            'metadata': {'kind': 'cumulative', 'verified': True, 'window': 'per_mission_year',
                'coverage_start': (self.now-timedelta(seconds=1)).isoformat(), 'coverage_end': self.now.isoformat()}},
            'cabin_co2': {'value': 2, 'unit': 'mmHg', 'metadata': {'verified': True, 'window': '1_hour_average',
                'coverage_start': (self.now-timedelta(minutes=59)).isoformat(), 'coverage_end': (self.now+timedelta(minutes=1)).isoformat()}}}))
        self.assertEqual(self.row(snap, 'nuclear_source_dose')['status'], 'needs_context')
        self.assertEqual(self.row(snap, 'cabin_co2')['status'], 'needs_context')

    def test_measured_cumulative_forecast_uses_differences_across_three_dates(self):
        start = self.now - timedelta(days=1)
        for value in (10, 11, 12):
            snap = self.monitor.ingest('A-101', self.packet({'nuclear_source_dose': {'value': value, 'unit': 'mSv',
                'metadata': {'kind': 'cumulative', 'verified': True, 'window': 'per_mission_year',
                    'coverage_start': start.isoformat(), 'coverage_end': self.now.isoformat()}}}))
            if value != 12:
                self.now += timedelta(days=1)
        forecast = next(f for f in snap['forecasts'] if f['key'] == 'nuclear_source_dose')
        self.assertEqual(forecast['status'], 'projected')
        self.assertEqual(forecast['daily_rate'], 1)
        self.assertEqual(forecast['current_total'], 12)
        self.assertEqual(forecast['days_to_threshold'], 28)
        self.now += timedelta(hours=25)
        stale_forecast = next(f for f in self.monitor.snapshot('A-101')['forecasts'] if f['key']=='nuclear_source_dose')
        self.assertEqual(stale_forecast['status'], 'insufficient_data')

    def test_reset_detected_beyond_buffer_and_survives_restart(self):
        start = self.now-timedelta(days=1)
        def dose(value):
            return {'nuclear_source_dose': {'value':value,'unit':'mSv','metadata':{'kind':'cumulative',
                'verified':True,'window':'per_mission_year','coverage_start':start.isoformat(),'coverage_end':self.now.isoformat()}}}
        self.monitor.ingest('A-101', self.packet(dose(10)))
        self.now += timedelta(minutes=2)
        self.monitor.tick()
        snap = self.monitor.ingest('A-101',self.packet(dose(1)))
        self.assertEqual(self.row(snap,'nuclear_source_dose')['status'],'needs_context')
        self.monitor.close()
        self.monitor = Monitor(Path(self.temp.name),ROOT/'config',ROOT/'profiles',clock=lambda:self.now)
        self.monitor.active_source['A-101']='simulation'
        snap = self.monitor.snapshot('A-101')
        self.assertEqual(self.row(snap,'nuclear_source_dose')['status'],'needs_context')
        self.now += timedelta(seconds=2)
        snap = self.monitor.ingest('A-101',self.packet(dose(2)))
        self.assertEqual(self.row(snap,'nuclear_source_dose')['status'],'needs_context')

    def test_daily_dose_intervals_reported_next_midnight_are_accumulated(self):
        self.now = self.now.replace(hour=0)
        self.monitor.ingest('A-101',self.packet())
        for _ in range(3):
            begin = self.now
            self.now += timedelta(days=1)
            snap = self.monitor.ingest('A-101',self.packet({'nuclear_source_dose':{'value':1,'unit':'mSv',
                'metadata':{'kind':'interval','verified':True,'coverage_start':begin.isoformat(),'coverage_end':self.now.isoformat()}}}))
        row = self.row(snap,'nuclear_source_dose')
        self.assertEqual(row['value'],3)
        self.assertEqual(row['status'],'normal')
        forecast = next(f for f in snap['forecasts'] if f['key']=='nuclear_source_dose')
        self.assertEqual(forecast['status'],'projected')
        self.assertEqual(forecast['daily_rate'],1)
        days = [r['day'] for r in self.monitor.history('A-101')['daily'] if r['key']=='nuclear_source_dose']
        self.assertEqual(days,['2026-11-15','2026-11-16','2026-11-17'])

    def test_restart_acquisition_watermark_rejects_old_and_duplicate_normals(self):
        packet = self.packet()
        self.monitor.ingest('A-101',packet)
        self.now += timedelta(seconds=10)
        newer = self.packet({'heart_rate':{'value':76,'unit':'bpm'}})
        self.monitor.ingest('A-101',newer)
        self.monitor.close()
        self.monitor = Monitor(Path(self.temp.name),ROOT/'config',ROOT/'profiles',clock=lambda:self.now)
        for old_packet in (packet,newer):
            with self.assertRaises(ValueError):
                self.monitor.ingest('A-101',old_packet)
        self.assertEqual(self.monitor.history('A-101')['daily'][0]['count'],2)
        self.now += timedelta(seconds=1)
        self.monitor.ingest('A-101',self.packet())
        self.assertEqual(self.monitor.history('A-101')['daily'][0]['count'],3)

    def test_stopped_stream_emits_one_technical_alert_then_can_recover(self):
        self.monitor.ingest('A-101',self.packet())
        self.now += timedelta(seconds=61)
        # UI snapshots may have purged raw values already; tick still detects loss.
        self.monitor.snapshot('A-101')
        self.monitor.tick()
        events = self.monitor.history('A-101')['events']
        stale = [e for e in events if e['kind']=='sensor_stale']
        self.assertEqual(len(stale),1)
        self.assertEqual(stale[0]['severity'],'TECHNICAL')
        self.assertEqual(stale[0]['key'],'heart_rate')
        self.monitor.tick()
        self.assertEqual(len([e for e in self.monitor.history('A-101')['events'] if e['kind']=='sensor_stale']),1)
        self.now += timedelta(seconds=1)
        self.monitor.ingest('A-101',self.packet())
        self.assertTrue(any(e['kind']=='recovery' and 'resumed' in e['message'] for e in self.monitor.history('A-101')['events']))
        self.now += timedelta(seconds=61)
        self.monitor.tick()
        self.assertEqual(len([e for e in self.monitor.history('A-101')['events'] if e['kind']=='sensor_stale']),2)

    def test_possible_arrest_finding_shows_treatment_only_for_current_valid_zero(self):
        snap = self.monitor.ingest('A-101',self.packet({'heart_rate':{'value':0,'unit':'bpm'}}))
        finding = next(f for f in snap['assessment']['findings'] if f['rule_id']=='HEART_RATE_ZERO')
        self.assertEqual(finding['level'],'EMERGENCY')
        self.assertTrue(finding['treatments'])
        self.assertIn('Possible',finding['name'])
        self.now += timedelta(seconds=2)
        snap = self.monitor.ingest('A-101',self.packet())
        self.assertFalse(any(f['rule_id']=='HEART_RATE_ZERO' for f in snap['assessment']['findings']))
        self.now += timedelta(seconds=2)
        snap = self.monitor.ingest('A-101',self.packet({'heart_rate':{'value':0,'unit':'bpm'}},quality='disconnected'))
        self.assertFalse(any(f['rule_id']=='HEART_RATE_ZERO' for f in snap['assessment']['findings']))


if __name__ == '__main__':
    unittest.main()
