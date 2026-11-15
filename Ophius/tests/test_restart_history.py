from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest

from ophius.monitor import Monitor
from ophius.report_simulation import simulate_report

ROOT=Path(__file__).resolve().parents[1]


class RestartHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.now=datetime(2026,11,15,12,tzinfo=timezone.utc)
        self.monitor=self.open()

    def open(self,restore=False):
        return Monitor(self.temp.name,ROOT/'config',ROOT/'profiles',clock=lambda:self.now,restore_source=restore)

    def tearDown(self):
        self.monitor.close();self.temp.cleanup()

    def ingest(self,source):
        self.monitor.ingest('A-101',{'timestamp':self.now.isoformat(),'packet_id':source+self.now.isoformat(),
            'source':source,'readings':{'heart_rate':{'value':72,'unit':'bpm'}}})

    def restart(self,restore=True):
        self.monitor.close();self.monitor=self.open(restore)
        return self.monitor.snapshot('A-101')

    def test_saved_simulations_restore_day_labs_dose_and_history_without_live_raws(self):
        self.ingest('simulation')
        simulate_report(self.monitor,'A-101',{'scope':'labs','scenario':'anemia'})
        simulate_report(self.monitor,'A-101',{'scope':'dose','scenario':'normal'})
        self.now+=timedelta(days=4)
        snap=self.restart()
        self.assertEqual(snap['active_source'],'simulation')
        self.assertEqual(snap['mission_day'],5)
        rows={r['key']:r for r in snap['readings']}
        self.assertEqual(rows['hemoglobin']['value'],10.4)
        self.assertIsNotNone(rows['nuclear_source_dose']['value'])
        self.assertIsNone(rows['heart_rate']['value'])
        self.assertEqual(snap['monitoring']['buffer_samples'],0)
        history=self.monitor.history('A-101')
        self.assertTrue(history['daily']);self.assertTrue(history['lab_reports']);self.assertTrue(history['events'])
        self.assertEqual(self.restart()['mission_day'],5)

    def test_normal_restart_keeps_observed_anchor_even_if_last_input_was_synthetic(self):
        self.ingest('jsonl')
        self.now+=timedelta(days=1)
        self.ingest('simulation')
        self.now+=timedelta(days=1)
        snap=self.restart(restore=False)
        self.assertEqual(snap['active_source'],'observed')
        self.assertEqual(snap['mission_day'],3)
        self.assertTrue(self.monitor.history('A-101')['daily'])

    def test_legacy_database_infers_latest_source_without_changing_anchor(self):
        self.ingest('jsonl')
        self.now+=timedelta(days=1)
        self.ingest('simulation')
        anchor=self.monitor.storage.get_anchor('A-101','simulation')
        with self.monitor.storage.connection:
            self.monitor.storage.connection.execute('DROP TABLE selected_sources')
        self.now+=timedelta(days=1)
        snap=self.restart()
        self.assertEqual(snap['active_source'],'simulation')
        self.assertEqual(snap['mission_day'],2)
        self.assertEqual(self.monitor.storage.get_anchor('A-101','simulation'),anchor)
        self.assertEqual(self.monitor.storage.selected_source('A-101'),'simulation')

    def test_testing_restores_last_observed_report_view_and_never_starts_unmeasured_profile(self):
        self.ingest('simulation')
        self.now+=timedelta(seconds=1)
        self.ingest('jsonl')
        snap=self.restart()
        self.assertEqual(snap['active_source'],'observed')
        self.assertEqual(snap['mission_day'],1)
        self.assertIsNone(self.monitor.snapshot('A-102')['mission_day'])
        self.assertEqual(self.monitor.snapshot('A-102')['active_source'],'simulation')


if __name__=='__main__':unittest.main()
