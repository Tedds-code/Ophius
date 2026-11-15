from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest

from astrohealth.monitor import Monitor
from astrohealth.report_simulation import simulate_report,measurement_connections,LAB_SCENARIOS

ROOT=Path(__file__).resolve().parents[1]


class ReportSimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.now=datetime(2026,11,15,12,tzinfo=timezone.utc)
        self.monitor=Monitor(Path(self.temp.name),ROOT/'config',ROOT/'profiles',clock=lambda:self.now)

    def tearDown(self):self.monitor.close();self.temp.cleanup()

    def simulate(self,aid='A-101',**payload):
        self.now+=timedelta(seconds=1)
        return simulate_report(self.monitor,aid,payload)

    def test_all_lab_measurements_for_both_profile_reference_bands(self):
        for aid in ['A-101','A-102']:
            snap=self.simulate(aid,scope='labs',scenario='normal')
            rows=[r for r in snap['readings'] if r['type']=='lab']
            self.assertEqual(len(rows),12)
            self.assertTrue(all(r['status']=='normal' for r in rows))
            self.assertEqual(snap['report_simulation']['measurement_count'],12)
            self.assertIsNone(self.monitor.storage.get_anchor(aid,'observed'))

    def test_named_lab_cases_trigger_linked_medical_findings(self):
        expected={'anemia':'B01','polycythemia':'B02','leukopenia':'B03','leukocytosis':'B04',
                  'thrombocytopenia':'B05','d_dimer':'B06','febrile_neutropenia':'B03'}
        for scenario,rule in expected.items():
            snap=self.simulate(scope='labs',scenario=scenario)
            finding=next(f for f in snap['assessment']['findings'] if f['rule_id']==rule)
            self.assertTrue(finding['treatments'])
            if scenario=='febrile_neutropenia':self.assertEqual(finding['level'],'EMERGENCY')

    def test_each_individual_lab_can_cross_each_configured_bound(self):
        specs=[r for r in self.monitor.kb.reading_keys() if r['category']=='blood_panel']
        for spec in specs:
            rule=self.monitor.kb.signals[self.monitor.kb.signal_name(spec['key'],'male')]
            for direction,bound in [('high','caution_above'),('low','caution_below')]:
                if rule.get(bound) is None:continue
                snap=self.simulate(scope='labs',scenario='single',key=spec['key'],direction=direction)
                row=next(r for r in snap['readings'] if r['key']==spec['key'])
                self.assertIn(row['status'],{'caution','critical'},(spec['key'],direction))

    def test_all_dose_quantities_are_assessed_with_explicit_synthetic_coverage(self):
        for scenario,status in [('normal','normal'),('high','critical'),('normal','normal'),('needs_context','needs_context')]:
            snap=self.simulate(scope='dose',scenario=scenario)
            keys={k for k,r in self.monitor.kb.signals.items() if r['category']=='radiation'}
            rows=[r for r in snap['readings'] if r['key'] in keys]
            self.assertEqual(len(rows),19)
            self.assertTrue(all(r['status']==status for r in rows),[(r['key'],r['status']) for r in rows])
            self.assertIsNone(self.monitor.storage.get_anchor('A-101','observed'))

    def test_every_dose_supports_individual_high_fixture(self):
        for key,rule in self.monitor.kb.signals.items():
            if rule['category']!='radiation':continue
            snap=self.simulate(scope='dose',scenario='single',key=key,direction='high')
            row=next(r for r in snap['readings'] if r['key']==key)
            self.assertEqual(row['status'],'critical',key)

    def test_connections_explain_rules_or_reference_only_and_scaled_limit(self):
        self.simulate(scope='labs',scenario='anemia')
        connection=measurement_connections(self.monitor,'A-101','hemoglobin')
        self.assertTrue(any(r['id']=='B01' and r['active'] for r in connection['linked_rules']))
        self.assertEqual(connection['reference']['unit'],'g/dL')
        self.simulate(scope='dose',scenario='normal')
        connection=measurement_connections(self.monitor,'A-101','nuclear_source_dose')
        self.assertEqual(connection['effective_limits']['critical_above'],40)
        self.assertFalse(connection['linked_rules'])
        self.assertIn('no dedicated diagnostic rule',connection['interpretation'])

    def test_invalid_requests_do_not_import_any_lab_reports(self):
        for payload in [{'scope':'labs','scenario':'single','key':'potassium'},
                        {'scope':'labs','scenario':'single','key':'d_dimer','direction':'low'},
                        {'scope':'labs','scenario':'made_up'},{'scope':'not_a_scope'}]:
            with self.assertRaises(ValueError):self.simulate(**payload)
        self.assertFalse(self.monitor.history('A-101')['lab_reports'])


if __name__=='__main__':unittest.main()
