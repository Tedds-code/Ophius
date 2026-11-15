"""Device adapter contracts, including regression cases from Fresh integration."""
import json
import math
import unittest

from ophius.engine import KnowledgeBase
from ophius.transport import normalize_packet, pulse_rate, strict_json


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase()

    def packet(self, sensor, data, **kwargs):
        return dict(sensor=sensor, timestamp='2026-11-15T12:00:00Z', data=data, **kwargs)

    def test_zero_vitals_are_preserved_for_immediate_monitor_warning(self):
        cases = [
            self.packet('ppg', {'heart_rate_bpm': 0, 'spo2_percent': 0}, calibration_id='demo'),
            self.packet('ecg', {'heart_rate_bpm': 0, 'qtc_ms': 0}),
            self.packet('blood_pressure', {'blood_pressure_systolic': 0, 'blood_pressure_diastolic': 0}),
        ]
        for packet in cases:
            with self.subTest(sensor=packet['sensor']):
                converted = normalize_packet(packet, self.kb)
                self.assertTrue(converted['readings'])
                self.assertTrue(all(row['value'] == 0 for row in converted['readings'].values()))

    def test_spo2_device_packet_requires_calibration_identifier(self):
        for calibration in (None, '', False, 123):
            with self.subTest(calibration=calibration), self.assertRaises(ValueError):
                normalize_packet(self.packet('ppg', {'spo2_percent': 98}, calibration_id=calibration), self.kb)

    def test_duplicate_keys_rejected_at_any_depth(self):
        for text in ('{"value":1,"value":2}', '{"a":{"value":1,"value":2}}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict_json(text)

    def test_nonfinite_literals_and_overflow_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e999', '-1e999'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                strict_json('{"value":' + value + '}')

    def test_nonfinite_fresh_measurement_rejected(self):
        for value in (math.nan, math.inf, -math.inf, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_packet(self.packet('ecg', {'heart_rate_bpm': value}), self.kb)

    def test_fresh_thermistor_wiring_conversion(self):
        adc = 2533
        resistance = 10000 * (4095-adc) / adc
        expected = 1/(1/298.15 + math.log(resistance/10000)/3950) - 273.15
        result = normalize_packet(self.packet('thermistor', {'adc_count': adc}), self.kb)
        self.assertAlmostEqual(result['readings']['skin_temperature']['value'], expected, places=6)
        self.assertGreater(expected, 35)

    def test_fractional_or_saturated_adc_rejected(self):
        for value in (0, 4095, 1234.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_packet(self.packet('thermistor', {'adc_count': value}), self.kb)

    def test_device_provenance_survives_normalization(self):
        packet = self.packet('ppg', {'heart_rate_bpm': 72, 'spo2_percent': 98},
                             device_id='demo-ppg', calibration_id='demo-cal', origin='simulated')
        converted = normalize_packet(packet, self.kb, channel='tcp')
        self.assertEqual(converted['source'], 'simulation')
        for metric in converted['readings'].values():
            self.assertEqual(metric['metadata']['device_id'], 'demo-ppg')
            self.assertEqual(metric['metadata']['calibration_id'], 'demo-cal')
            self.assertEqual(metric['metadata']['origin'], 'simulated')
            self.assertEqual(metric['metadata']['sensor'], 'ppg')

    def test_fresh_report_calendar_dates_become_exact_interval(self):
        packet = self.packet('dose_report', {'coverage_window': '30_days', 'lens_dose_30d': 100,
            'coverage_start': '2026-10-01', 'coverage_end': '2026-10-30', 'verified': True})
        metric = normalize_packet(packet, self.kb)['readings']['lens_dose_30d']
        start, end = metric['metadata']['coverage_start'], metric['metadata']['coverage_end']
        from datetime import datetime
        self.assertEqual((datetime.fromisoformat(end.replace('Z', '+00:00')) -
                          datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds(), 30*86400)

    def test_packet_hash_is_stable_for_identical_input(self):
        packet = self.packet('ecg', {'heart_rate_bpm': 72})
        self.assertEqual(normalize_packet(packet, self.kb)['packet_id'],
                         normalize_packet(json.loads(json.dumps(packet)), self.kb)['packet_id'])

    def test_unsupported_sensor_and_dose_names_rejected(self):
        for packet in (self.packet('imu', {'accel_x': 1}),
                       self.packet('dose_report', {'coverage_window': 'career', 'generic_counts': 123}),
                       self.packet('lab_analyzer', {'potassium': 1})):
            with self.subTest(sensor=packet['sensor']), self.assertRaises(ValueError):
                normalize_packet(packet, self.kb)

    def test_flat_waveform_is_signal_failure_not_zero_heart_rate(self):
        with self.assertRaises(ValueError):
            pulse_rate([0]*100, 50)

    def test_hourly_co2_metadata_is_explicit_and_ppm_is_not_converted(self):
        with self.assertRaises(ValueError):
            normalize_packet(self.packet('co2', {'co2_ppm': 1000}), self.kb)
        result = normalize_packet(self.packet('co2', {'co2_1h_mmhg': 2.0,
            'sample_period_minutes': 60, 'verified': True,
            'coverage_start': '2026-11-15T11:00:00Z', 'coverage_end': '2026-11-15T12:00:00Z'}), self.kb)
        metric = result['readings']['cabin_co2']
        self.assertEqual(metric['unit'], 'mmHg')
        self.assertEqual(metric['metadata']['window'], '1_hour_average')
        self.assertTrue(metric['metadata']['verified'])


if __name__ == '__main__':
    unittest.main()
