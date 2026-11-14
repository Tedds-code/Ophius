# Made in cooperation with ChatGPT
# File: tests/test_sessions.py
"""Tests for durable session grouping and default summaries."""

import tempfile
import unittest
from pathlib import Path

from astro_health.cli import HealthCLI
from astro_health.database import Database
from astro_health.health_service import HealthService
from astro_health.models import MeasurementValue, Reading
from astro_health.session_store import SessionStore
from astro_health.sensor_simulators import make_simulated_packet


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / 'monitor.db')
        self.db.initialize()
        self.service = HealthService(self.db)
        self.sessions = SessionStore(self.db)
        self.sessions.initialize()
        self.messages = []

    def reading(self, value=32.5, name='skin_temperature', unit='degC'):
        return Reading(
            source='manual',
            measurements=(MeasurementValue(name, value, unit),),
        )

    def cli(self, replies):
        iterator = iter(replies)
        return HealthCLI(
            self.service,
            input_function=lambda prompt: next(iterator),
            output_function=self.messages.append,
            sensor_realtime=False,
        )

    def test_migration_preserves_legacy_readings(self):
        old_id = self.service.record_reading(self.reading())
        self.sessions.initialize()  # idempotent
        self.assertEqual(self.service.get_reading(old_id).id, old_id)
        self.assertEqual(self.sessions.list_sessions(), [])

    def test_start_and_finish_empty_session(self):
        sid = self.sessions.start()
        self.assertEqual(self.sessions.get_session(sid).status, 'active')
        self.sessions.finish(sid)
        result = self.sessions.get_session(sid)
        self.assertEqual(result.status, 'completed')
        self.assertIsNotNone(result.ended_at)
        self.assertEqual(result.reading_count, 0)

    def test_attach_multiple_readings_to_one_session(self):
        sid = self.sessions.start()
        identifiers = [self.service.record_reading(self.reading(n)) for n in (30, 31, 32)]
        for rid in identifiers:
            self.sessions.attach_reading(sid, rid)
        self.assertEqual(self.sessions.get_session(sid).reading_count, 3)
        self.assertEqual([r.id for r in self.sessions.readings_for_session(sid)], identifiers)
        self.assertEqual(self.sessions.summary(sid)['skin_temperature'].value, 32)

    def test_summary_skips_invalid_and_preserves_detail(self):
        sid = self.sessions.start()
        first = self.service.record_reading(self.reading(33))
        self.sessions.attach_reading(sid, first)
        # structurally invalid units / NaN aren't chosen for the summary
        bad = self.service.record_reading(self.reading(float('nan')))
        self.sessions.attach_reading(sid, bad)
        self.assertEqual(self.sessions.get_session(sid).reading_count, 2)
        self.assertEqual(self.sessions.summary(sid)['skin_temperature'].reading_id, first)

    def test_blood_pressure_summary_never_mixes_incomplete_readings(self):
        sid = self.sessions.start()
        full = self.service.record_reading(Reading(
            source='manual',
            measurements=(
                MeasurementValue('systolic_pressure', 120, 'mmHg'),
                MeasurementValue('diastolic_pressure', 80, 'mmHg'),
            ),
        ))
        self.sessions.attach_reading(sid, full)
        partial = self.service.record_reading(Reading(
            source='manual',
            measurements=(MeasurementValue('systolic_pressure', 130, 'mmHg'),),
        ))
        self.sessions.attach_reading(sid, partial)
        summary = self.sessions.summary(sid)
        self.assertEqual(summary['systolic_pressure'].value, 120)
        self.assertEqual(summary['diastolic_pressure'].value, 80)
        self.assertEqual(summary['systolic_pressure'].reading_id, full)

    def test_recover_active_session_and_preserve_readings(self):
        sid = self.sessions.start()
        rid = self.service.record_reading(self.reading())
        self.sessions.attach_reading(sid, rid)
        self.assertEqual(self.sessions.recover_interrupted(), 1)
        session = self.sessions.get_session(sid)
        self.assertEqual(session.status, 'interrupted')
        self.assertEqual(session.reading_count, 1)
        self.assertEqual(self.sessions.recover_interrupted(), 0)

    def test_no_duplicate_association(self):
        sid = self.sessions.start()
        rid = self.service.record_reading(self.reading())
        self.sessions.attach_reading(sid, rid)
        with self.assertRaises(Exception):
            self.sessions.attach_reading(sid, rid)

    def test_cannot_attach_to_closed_session(self):
        sid = self.sessions.start()
        rid = self.service.record_reading(self.reading())
        self.sessions.finish(sid)
        with self.assertRaises(ValueError):
            self.sessions.attach_reading(sid, rid)

    def test_cli_exit_8_saves_session_even_with_no_tests(self):
        self.cli(['8']).run()
        sessions = self.sessions.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].status, 'completed')
        self.assertEqual(sessions[0].reading_count, 0)

    def test_cli_ctrl_c_saves_session(self):
        def interrupt(_prompt):
            raise KeyboardInterrupt
        cli = HealthCLI(self.service, input_function=interrupt,
                        output_function=self.messages.append)
        cli.run()
        self.assertEqual(self.sessions.list_sessions()[0].status, 'completed')

    def test_cli_manual_data_attaches_to_session(self):
        self.cli(['1', '1', '36.8', 'yes', '8']).run()
        session = self.sessions.list_sessions()[0]
        self.assertEqual(session.reading_count, 1)
        self.assertEqual(self.sessions.summary(session.id)['temperature'].value, 36.8)

    def test_cli_sensor_packets_attached_to_one_session(self):
        self.cli(['4', '1', '3', '8']).run()
        session = self.sessions.list_sessions()[0]
        self.assertEqual(session.reading_count, 3)
        self.assertEqual(len(self.sessions.readings_for_session(session.id)), 3)
        self.assertTrue((self.db.database_path.parent / 'sensor_logs' / 'sensor_packets.jsonl').is_file())

    def test_cli_file_import_one_session(self):
        path = Path(self.tmp.name) / 'sensor_input.jsonl'
        path.write_text('\n'.join(make_simulated_packet(s).to_json()
                         for s in ('thermistor', 'co2', 'imu')) + '\n', encoding='utf-8')
        self.cli(['5', str(path), '8']).run()
        session = self.sessions.list_sessions()[0]
        self.assertEqual(session.reading_count, 3)
        keys = self.sessions.summary(session.id)
        self.assertTrue({'skin_temperature', 'co2_concentration', 'acceleration_x'} <= set(keys))

    def test_cli_summary_missing_fields_display_dash(self):
        self.cli(['2', '1', 'no', '8']).run()
        self.assertIn('Heart rate: -', self.messages)

    def test_legacy_record_still_accessible(self):
        rid = self.service.record_reading(self.reading())
        self.cli(['2', f'r{rid}', '8']).run()
        self.assertTrue(any(f'Reading ID: {rid}' in m for m in self.messages))


if __name__ == '__main__':
    unittest.main()
