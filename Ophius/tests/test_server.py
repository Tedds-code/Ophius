"""Exercise the real local HTTP boundary with an isolated monitor database."""
from datetime import datetime, timedelta, timezone
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from ophius.monitor import Monitor
from ophius.server import make_server
from ophius.simulation import Simulator

ROOT = Path(__file__).resolve().parents[1]


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = datetime.now(timezone.utc)
        self.monitor = Monitor(Path(self.temp.name), ROOT/'config', ROOT/'profiles', clock=lambda: self.now)
        self.simulator = Simulator(self.monitor)
        self.server = make_server(self.monitor, self.simulator, port=0, testing_mode=getattr(self,'testing_mode',True))
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.count = 0

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.monitor.close()
        self.temp.cleanup()

    def request(self, method, path, payload=None, raw=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        extra = {'Content-Type': 'application/json'}
        extra.update(headers or {})
        body = raw if raw is not None else (json.dumps(payload) if payload is not None else None)
        try:
            connection.request(method, path, body=body, headers=extra)
            response = connection.getresponse()
            data = response.read()
            content_type = response.getheader('Content-Type', '')
            parsed = json.loads(data) if content_type.startswith('application/json') else data
            return response.status, parsed
        finally:
            connection.close()

    def packet(self, values=None, when=None):
        self.count += 1
        return {'packet_id': f'http-{self.count}', 'timestamp': (when or self.now).isoformat(),
                'source': 'jsonl', 'readings': values or {'heart_rate': {'value': 72, 'unit': 'bpm'}}}

    def get(self, aid='A-101'):
        code, value = self.request('GET', '/api/astronauts/'+aid)
        self.assertEqual(code, 200, value)
        return value

    def row(self, snapshot, key):
        return next(row for row in snapshot['readings'] if row['key'] == key)

    def test_initial_unknown_and_baselines_do_not_seed_live_values(self):
        snap = self.get()
        self.assertEqual(snap['assessment']['overall'], 'UNKNOWN')
        self.assertIsNone(snap['mission_day'])
        heart = self.row(snap, 'heart_rate')
        self.assertIsNone(heart['value'])
        self.assertEqual(heart['baseline']['value'], 62)
        self.assertEqual(heart['status'], 'missing')
        code, profiles = self.request('GET', '/api/astronauts')
        self.assertEqual(code, 200)
        self.assertEqual({p['id'] for p in profiles}, {'A-101', 'A-102'})
        self.assertTrue(all(p['overall'] == 'UNKNOWN' for p in profiles))

    def test_meta_exposes_updated_catalog_without_greek_dependency(self):
        code, data = self.request('GET', '/api/meta')
        self.assertEqual(code, 200)
        self.assertEqual(len(data['rules']), 38)
        self.assertEqual(len(data['treatment_library']), 42)
        self.assertEqual(data['buffer_seconds'], 60)
        self.assertNotIn('i18n_el', data)

    def test_malformed_nonfinite_and_duplicate_json_rejected_without_state_change(self):
        bad = ['{', '[]', '{"packet_id":"one","packet_id":"two"}',
               '{"value":NaN}', '{"value":Infinity}', '{"value":1e999}',
               '{"readings":{"heart_rate":{"value":1,"value":2}}}']
        for raw in bad:
            with self.subTest(raw=raw):
                code, data = self.request('POST', '/api/astronauts/A-101/ingest', raw=raw)
                self.assertEqual(code, 400, data)
                self.assertIn('error', data)
        self.assertIsNone(self.get()['mission_day'])
        self.assertIsNone(self.row(self.get(), 'heart_rate')['value'])

    def test_cross_origin_and_invalid_host_blocked(self):
        for headers in ({'Origin': 'https://example.invalid'}, {'Origin': 'null'},
                        {'Host': 'example.invalid:'+str(self.server.server_port)}):
            with self.subTest(headers=headers):
                code, _ = self.request('GET', '/api/astronauts', headers=headers)
                self.assertEqual(code, 403)
        allowed = f'http://localhost:{self.server.server_port}'
        code, _ = self.request('GET', '/api/meta', headers={'Origin': allowed})
        self.assertEqual(code, 200)

    def test_write_requires_json_content_type(self):
        code, data = self.request('POST', '/api/astronauts/A-101/ingest',
                                  raw='{}', headers={'Content-Type': 'text/plain'})
        self.assertEqual(code, 400, data)

    def test_rejected_ingest_is_atomic(self):
        code, _ = self.request('POST', '/api/astronauts/A-101/ingest',
                               self.packet(when=self.now-timedelta(seconds=2)))
        self.assertEqual(code, 200)
        invalid = self.packet({'heart_rate': {'value': 200, 'unit': 'bpm'},
                               'spo2': {'value': 'bad', 'unit': '%'}}, when=self.now-timedelta(seconds=1))
        code, data = self.request('POST', '/api/astronauts/A-101/ingest', invalid)
        self.assertEqual(code, 400, data)
        snap = self.get()
        self.assertEqual(self.row(snap, 'heart_rate')['value'], 72)
        self.assertIsNone(self.row(snap, 'spo2')['value'])
        self.assertEqual(snap['alerts'], [])
        code, history = self.request('GET', '/api/astronauts/A-101/history')
        self.assertEqual(code, 200)
        self.assertEqual(history['events'], [])

    def test_duplicate_packet_is_rejected(self):
        packet = self.packet()
        code, _ = self.request('POST', '/api/astronauts/A-101/ingest', packet)
        self.assertEqual(code, 200)
        code, data = self.request('POST', '/api/astronauts/A-101/ingest', packet)
        self.assertEqual(code, 400, data)

    def test_simulation_once_and_qtc_display_updated_treatment(self):
        path = '/api/astronauts/A-101/simulate'
        code, normal = self.request('POST', path, {'action': 'once', 'mode': 'normal'})
        self.assertEqual(code, 200, normal)
        self.assertEqual(normal['active_source'], 'simulation')
        self.assertEqual(normal['assessment']['overall'], 'NORMAL')
        self.assertEqual(self.row(normal, 'heart_rate')['source'], 'simulation')
        self.now += timedelta(seconds=1)
        code, bad = self.request('POST', path, {'action': 'once', 'mode': 'qtc'})
        self.assertEqual(code, 200, bad)
        self.assertEqual(self.row(bad, 'qtc_interval')['status'], 'critical')
        finding = next(f for f in bad['assessment']['findings'] if f['rule_id'] == 'QTC')
        self.assertEqual(finding['treatment_source'], 'treatment.json')
        self.assertTrue(finding['treatments'])
        self.assertEqual(finding['condition_id'], 'qtc_interval_prolongation')

    def test_manual_lab_import_triggers_blood_rule_and_ignores_unsupported_electrolytes(self):
        report = {'report_id': 'http-lab', 'timestamp': self.now.isoformat(), 'synthetic': False,
                  'measurements': {'hemoglobin': {'value': 11, 'unit': 'g/dL'},
                                   'potassium': {'value': 1, 'unit': 'mEq/L'},
                                   'magnesium': {'value': 0.1, 'unit': 'mg/dL'}}}
        code, snap = self.request('POST', '/api/astronauts/A-101/lab', report)
        self.assertEqual(code, 200, snap)
        self.assertEqual(snap['active_source'], 'observed')
        self.assertEqual(set(snap['import']['ignored_measurements']), {'potassium', 'magnesium'})
        anemia = next(f for f in snap['assessment']['findings'] if f['rule_id'] == 'B01')
        self.assertTrue(anemia['treatments'])
        self.assertFalse(any(f['condition_id'] in {'hypokalemia', 'hypomagnesemia_magnesium_deficiency'}
                             for f in snap['assessment']['findings']))
        self.assertEqual(self.row(snap, 'hemoglobin')['type'], 'lab')
        code, history = self.request('GET', '/api/astronauts/A-101/history')
        self.assertEqual(code, 200)
        self.assertTrue(history.get('lab_reports', history.get('labs')))

    def test_electrolyte_only_report_has_no_threshold_supported_measurements(self):
        code, data = self.request('POST', '/api/astronauts/A-101/lab', {
            'timestamp': self.now.isoformat(), 'measurements': {'potassium': {'value': 1, 'unit': 'mEq/L'}}})
        self.assertEqual(code, 400, data)
        self.assertEqual(self.get()['assessment']['findings'], [])

    def test_warning_acknowledgement_is_profile_scoped(self):
        code, snap = self.request('POST', '/api/astronauts/A-101/ingest',
                                  self.packet({'spo2': {'value': 89, 'unit': '%'}}))
        self.assertEqual(code, 200, snap)
        alert = next(event for event in snap['alerts'] if event['kind'] == 'threshold')
        code, _ = self.request('POST', '/api/astronauts/A-102/ack', {'event_id': alert['id']})
        self.assertEqual(code, 404)
        code, acknowledged = self.request('POST', '/api/astronauts/A-101/ack', {'event_id': alert['id']})
        self.assertEqual(code, 200, acknowledged)
        self.assertFalse(any(event['id'] == alert['id'] for event in acknowledged['alerts']))
        self.assertEqual(self.row(acknowledged, 'spo2')['status'], 'critical')

    def test_static_files_load_and_traversal_cannot_read_config(self):
        code, html = self.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn(b'<!doctype html>', html.lower())
        for path in ('/../config/thresholds.json', '/%2e%2e/config/thresholds.json',
                     '/%2e%2e/profiles/A-101.json'):
            with self.subTest(path=path):
                code, _ = self.request('GET', path)
                self.assertEqual(code, 404)

    def test_medication_allergy_guard_cannot_be_bypassed_through_api(self):
        base='/api/astronauts/A-101'
        code,check=self.request('POST',base+'/medication-check',{'medication':'amoxicillin'})
        self.assertEqual(code,200)
        self.assertTrue(check['blocked'])
        code,error=self.request('POST',base+'/medication',{'medication':'amoxicillin','recording_allowed':True})
        self.assertEqual(code,400)
        self.assertIn('blocked',error['error'])
        code,snap=self.request('PUT',base+'/allergies',{'allergies':['cetirizine']})
        self.assertEqual(code,200)
        code,check=self.request('POST',base+'/medication-check',{'medication':'cetirizine'})
        self.assertTrue(check['blocked'])
        code,_=self.request('GET','/app.js')
        self.assertEqual(code,200)

    def test_conditional_mission_forecast_separate_from_current_alarm(self):
        when = self.now-timedelta(seconds=1)
        packet = self.packet({'nuclear_source_dose': {'value': 35, 'unit': 'mSv', 'metadata': {
            'kind': 'cumulative', 'verified': True, 'window': 'per_mission_year',
            'coverage_start': (when-timedelta(days=10)).isoformat(), 'coverage_end': when.isoformat()}}}, when=when)
        code, snap = self.request('POST', '/api/astronauts/A-101/ingest', packet)
        self.assertEqual(code, 200, snap)
        before = len(snap['alerts'])
        code, result = self.request('POST', '/api/astronauts/A-101/forecast', {
            'key': 'nuclear_source_dose', 'unit': 'mSv', 'daily_rate': 1, 'horizon_days': 21})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['status'], 'projected')
        self.assertEqual(result['threshold'], 40)
        self.assertEqual(result['days_to_threshold'], 5)
        self.assertTrue(result['crosses_within_horizon'])
        self.assertEqual(len(self.get()['alerts']), before)

    def test_forecast_missing_context_and_wrong_units(self):
        path = '/api/astronauts/A-101/forecast'
        code, result = self.request('POST', path, {'key': 'nuclear_source_dose', 'unit': 'mSv', 'daily_rate': 1})
        self.assertEqual(code, 200)
        self.assertEqual(result['status'], 'insufficient_data')
        code, _ = self.request('POST', path, {'key': 'nuclear_source_dose', 'unit': 'mGy', 'daily_rate': 1})
        self.assertEqual(code, 400)


class NormalDesktopModeTests(unittest.TestCase):
    testing_mode = False
    setUp = ServerTests.setUp
    tearDown = ServerTests.tearDown
    request = ServerTests.request
    packet = ServerTests.packet
    get = ServerTests.get
    row = ServerTests.row

    def test_normal_mode_blocks_both_simulation_endpoints_without_writing_data(self):
        code, meta = self.request('GET','/api/meta')
        self.assertEqual(code,200)
        self.assertFalse(meta['testing_mode'])
        self.assertEqual(meta['simulation_modes'],[])
        self.assertEqual(meta['lab_scenarios'],{})
        for path,payload in [('simulate',{'action':'once','mode':'critical'}),
                             ('simulate-report',{'scope':'labs','scenario':'anemia'}),
                             ('simulate-report',{'scope':'dose','scenario':'high'})]:
            code, result=self.request('POST','/api/astronauts/A-101/'+path,payload)
            self.assertEqual(code,403,result)
        history=self.monitor.history('A-101')
        self.assertFalse(history['events'])
        self.assertFalse(history['lab_reports'])
        self.assertFalse(history['daily'])

    def test_normal_mode_rejects_explicitly_synthetic_imports(self):
        packet=self.packet();packet['source']='simulation'
        code,_=self.request('POST','/api/astronauts/A-101/ingest',packet)
        self.assertEqual(code,403)
        packet=self.packet();packet['readings']['heart_rate']['metadata']={'synthetic_coverage':True}
        code,_=self.request('POST','/api/astronauts/A-101/ingest',packet)
        self.assertEqual(code,403)
        packet=self.packet();packet['readings']['heart_rate']['metadata']={'origin':'simulated'}
        code,_=self.request('POST','/api/astronauts/A-101/ingest',packet)
        self.assertEqual(code,403)
        report={'timestamp':self.now.isoformat(),'synthetic':True,'report_id':'synthetic-normal',
                'measurements':{'hemoglobin':{'value':11,'unit':'g/dL'}}}
        code,_=self.request('POST','/api/astronauts/A-101/lab',report)
        self.assertEqual(code,403)
        self.assertEqual(self.get()['active_source'],'observed')
        self.assertIsNone(self.get()['mission_day'])

    def test_normal_mode_still_assesses_sensor_and_manual_lab_values(self):
        code,snap=self.request('POST','/api/astronauts/A-101/ingest',self.packet())
        self.assertEqual(code,200,snap)
        self.assertEqual(self.row(snap,'heart_rate')['value'],72)
        report={'timestamp':self.now.isoformat(),'report_id':'observed-normal',
                'measurements':{'hemoglobin':{'value':11,'unit':'g/dL'}}}
        code,snap=self.request('POST','/api/astronauts/A-101/lab',report)
        self.assertEqual(code,200,snap)
        self.assertEqual(snap['active_source'],'observed')
        self.assertTrue(any(f['rule_id']=='B01' for f in snap['assessment']['findings']))


if __name__ == '__main__':
    unittest.main()
