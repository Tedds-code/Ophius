from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from ophius.monitor import Monitor
from ophius.simulation import Simulator
from make_demo_reports import documents
from setup_desktop import install_linux, install_windows, linux_entry

ROOT = Path(__file__).resolve().parents[1]


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.now = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
        self.monitor = Monitor(self.path/'data', ROOT/'config', ROOT/'profiles', clock=lambda: self.now)

    def tearDown(self):
        self.monitor.close()
        self.temp.cleanup()

    def test_continuous_simulator_covers_every_live_card_with_explicit_co2_window(self):
        snap = Simulator(self.monitor)._send('A-101', 'normal', 0)
        live = {r['key']: r for r in snap['readings'] if r['key'] in {
            'heart_rate', 'spo2', 'blood_pressure_systolic', 'blood_pressure_diastolic',
            'qtc_interval', 'skin_temperature', 'cabin_co2'}}
        self.assertEqual(len(live), 7)
        self.assertTrue(all(r['value'] is not None and r['status'] == 'normal' for r in live.values()))
        co2 = self.monitor.last[('A-101', 'simulation')]['cabin_co2']
        self.assertEqual(co2['metadata']['window'], '1_hour_average')
        self.assertTrue(co2['metadata']['synthetic_coverage'])
        self.assertEqual(snap['monitoring']['source'], 'simulation')
        self.assertFalse(self.monitor.history('A-101')['lab_reports'])

    def test_high_co2_simulation_warns_without_inventing_real_exposure(self):
        snap = Simulator(self.monitor)._send('A-101', 'co2', 0)
        row = next(r for r in snap['readings'] if r['key'] == 'cabin_co2')
        self.assertEqual(row['status'], 'critical')
        self.assertTrue(any(a.get('key') == 'cabin_co2' for a in snap['alerts']))
        self.assertIsNone(self.monitor.storage.get_anchor('A-101', 'observed'))

    def test_generated_reports_cover_all_threshold_backed_lab_and_dose_quantities(self):
        reports = documents(self.now)
        labs = reports['blood_panel_all_supported.json']
        self.assertEqual(len(labs['measurements']), 12)
        self.assertEqual(labs['measurements']['d_dimer']['unit'], 'mg/L')
        snap = self.monitor.import_lab('A-101', labs)
        self.assertFalse(snap['assessment']['findings'])
        dose_keys = set()
        for filename, report in reports.items():
            if filename.startswith('dose_'):
                dose_keys.update(report['readings'])
                self.monitor.ingest('A-101', report)
        expected = {key for key, rule in self.monitor.kb.signals.items() if rule['category'] == 'radiation'}
        self.assertEqual(dose_keys, expected)
        self.assertEqual(len(dose_keys), 19)

    def test_updated_d_dimer_limits_and_units_drive_sex_specific_finding(self):
        for aid, value, expected in [('A-101', .45, True), ('A-102', .45, False)]:
            snap = self.monitor.import_lab(aid, {'timestamp': self.now.isoformat(),
                'measurements': {'d_dimer': {'value': value, 'unit': 'mg/L'}}})
            self.assertEqual(any(f['rule_id'] == 'B06' for f in snap['assessment']['findings']), expected)
        with self.assertRaisesRegex(ValueError, 'mg/L'):
            self.monitor.import_lab('A-101', {'timestamp': self.now.isoformat(),
                'measurements': {'d_dimer': {'value': 25, 'unit': 'mg/dL'}}})

    def test_condition_duration_remains_manually_enterable(self):
        self.assertIn('symptom_duration_hours', self.monitor.kb.meta()['derived'])
        snap = self.monitor.update_symptoms('A-101', {'readings': {'symptom_duration_hours': 12}})
        self.assertEqual(snap['state']['readings']['symptom_duration_hours'], 12)
        self.assertIsNone(snap['mission_day'])

    def test_legacy_unit_report_and_schema_upgrade_preserve_history_without_mixing(self):
        self.monitor.close()
        old_config = self.path/'old-config'
        shutil.copytree(ROOT/'config', old_config)
        thresholds = json.loads((old_config/'thresholds.json').read_text())
        for sex, limit in [('male', 40), ('female', 50)]:
            thresholds['signals']['d_dimer_'+sex].update(unit='mg/dL', caution_above=limit)
        (old_config/'thresholds.json').write_text(json.dumps(thresholds))
        self.monitor = Monitor(self.path/'data', old_config, ROOT/'profiles', clock=lambda: self.now)
        self.monitor.import_lab('A-101', {'timestamp': self.now.isoformat(),
            'measurements': {'d_dimer': {'value': 25, 'unit': 'mg/dL'}}})
        self.monitor.close()
        database = self.path/'data'/'astrohealth.sqlite3'
        with sqlite3.connect(database) as c:
            c.execute('ALTER TABLE daily RENAME TO daily_new')
            c.execute('CREATE TABLE daily (session_id TEXT, measurement_key TEXT, unit TEXT, statistics TEXT, PRIMARY KEY(session_id,measurement_key))')
            c.execute('INSERT INTO daily SELECT * FROM daily_new')
            c.execute('DROP TABLE daily_new')
            c.execute('PRAGMA user_version=1')
        self.monitor = Monitor(self.path/'data', ROOT/'config', ROOT/'profiles', clock=lambda: self.now)
        snap = self.monitor.snapshot('A-101')
        row = next(r for r in snap['readings'] if r['key'] == 'd_dimer')
        self.assertEqual(row['status'], 'needs_context')
        self.assertFalse(any(f['rule_id'] == 'B06' for f in snap['assessment']['findings']))
        self.now += timedelta(seconds=1)
        self.monitor.import_lab('A-101', {'timestamp': self.now.isoformat(),
            'measurements': {'d_dimer': {'value': .3, 'unit': 'mg/L'}}})
        self.monitor.close()
        self.monitor = Monitor(self.path/'data', ROOT/'config', ROOT/'profiles', clock=lambda: self.now)
        rows = [r for r in self.monitor.history('A-101')['daily'] if r['key'] == 'd_dimer']
        self.assertEqual({r['unit']: r['mean'] for r in rows}, {'mg/dL': 25, 'mg/L': .3})


class DesktopShortcutTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux desktop file integration")
    def test_linux_shortcut_installation_handles_spaces_without_running_app(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict('os.environ', {'XDG_DATA_HOME': str(root/'local share')}), patch('setup_desktop.shutil.which', return_value=None):
                paths = install_linux(root/'My Desktop')
            self.assertEqual(len(paths), 2)
            for path in paths:
                text = path.read_text()
                self.assertIn('launch_desktop.py', text)
                self.assertIn('Terminal=false', text)
                self.assertTrue(path.stat().st_mode & 0o111)
            entry = linux_entry(root/'App With Spaces'/'100%')
            self.assertIn('100%%/launch_desktop.py"', entry)

    def test_windows_shortcut_uses_native_desktop_folder_and_literal_arguments(self):
        from types import SimpleNamespace
        with patch('setup_desktop.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='C:\\Desktop\\Ophius.lnk\n', stderr='')) as run:
            paths = install_windows()
        command = run.call_args.args[0]
        self.assertIn('DesktopDirectory', command[-1])
        self.assertIn('CreateShortcut', command[-1])
        self.assertIn('launch_desktop.py', run.call_args.kwargs['env']['OPHIUS_ARGUMENTS'])
        self.assertEqual(str(paths[0]), 'C:\\Desktop\\Ophius.lnk')


if __name__ == '__main__':
    unittest.main()
