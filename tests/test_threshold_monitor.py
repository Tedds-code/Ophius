# Made in cooperation with ChatGPT
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from astro_health.threshold_monitor import load_thresholds, evaluate_reading
from astro_health.sensor_packets import SensorPacket
from astro_health.sensor_processing import process_packet

class ThresholdMonitorTests(unittest.TestCase):
    def setUp(self):
        self.config = load_thresholds('config/thresholds.json')

    def packet(self, sensor, data):
        return SensorPacket.from_dict({'sensor':sensor,'timestamp':'2026-11-14T09:00:00Z','data':data})

    def test_name_mapping_and_units(self):
        self.assertEqual(self.config['signals']['cumulative_effective_dose']['measurement_type'],'career_effective_dose')
        self.assertEqual(self.config['signals']['cabin_co2']['unit'],'mmHg')
        self.assertFalse(self.config['signals']['cabin_co2']['enabled_for_comparison'])

    def test_career_requires_explicit_coverage(self):
        packet=self.packet('radiation',{'measurement_basis':'nasa_effective_dose_model','radiation_source':'other','cumulative_effective_dose':700})
        reading=process_packet(packet).reading
        result=evaluate_reading(reading,self.config)[0]
        self.assertEqual(result['status'],'insufficient_context')
        result=evaluate_reading(reading,self.config,full_career_history=True)[0]
        self.assertEqual(result['status'],'critical')
        self.assertTrue(result['reference_verified'])

    def test_lens_window_not_guessed(self):
        packet=self.packet('radiation',{'measurement_basis':'nasa_effective_dose_model','radiation_source':'other','lens_dose':1500})
        reading=process_packet(packet).reading
        self.assertTrue(all(r['status']=='insufficient_context' for r in evaluate_reading(reading,self.config)))
        vals=evaluate_reading(reading,self.config,dose_window='30_days')
        self.assertEqual(next(v for v in vals if v['rule']=='lens_dose_30d')['status'],'critical')

    def test_nuclear_requires_duration(self):
        packet=self.packet('radiation',{'measurement_basis':'nasa_effective_dose_model','radiation_source':'nuclear_technology','nuclear_source_dose':15})
        reading=process_packet(packet).reading
        self.assertEqual(evaluate_reading(reading,self.config)[0]['status'],'insufficient_context')
        self.assertEqual(evaluate_reading(reading,self.config,mission_days=180,mission_cumulative_verified=True)[0]['status'],'critical')

if __name__=='__main__':unittest.main()
