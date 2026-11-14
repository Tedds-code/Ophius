# Made in cooperation with ChatGPT
import unittest
from datetime import datetime, timezone
from astro_health.sensor_packets import SensorPacket
from astro_health.sensor_processing import process_packet, ProcessingError
from astro_health.sensor_simulators import make_simulated_packet
from astro_health.fixed_tests import FIELDS_BY_MEASUREMENT
from astro_health.radiation import NASA_MEASUREMENT_FIELDS

T = datetime(2026, 11, 14, tzinfo=timezone.utc)

class StrictRadiationTests(unittest.TestCase):
    def pkt(self, sensor='radiation', **data):
        return SensorPacket(sensor=sensor, timestamp=T, data=data)

    def test_only_seven_catalog_quantities(self):
        self.assertEqual(len(NASA_MEASUREMENT_FIELDS), 7)
        for name in ('radiation_counts','radiation_dose','radiation_dose_rate'):
            self.assertNotIn(name, FIELDS_BY_MEASUREMENT)

    def test_all_simulated_fields(self):
        fields = set()
        for i in range(4):
            p = make_simulated_packet('radiation', i)
            fields.update(set(p.data) & set(NASA_MEASUREMENT_FIELDS))
            self.assertNotIn('particle_type', p.data)
            process_packet(p)
        self.assertEqual(fields, set(NASA_MEASUREMENT_FIELDS)-{'daily_gcr_dose_rate'})
        for i in range(2):
            p = make_simulated_packet('radiation_environment',i)
            self.assertEqual(set(p.data) & set(NASA_MEASUREMENT_FIELDS), {'daily_gcr_dose_rate'})
            process_packet(p)

    def test_reject_old_particle_and_counts(self):
        for data in ({'particle_type':'proton','dose_rate_uSv_h':0.1},
                     {'counts':5}, {'dose_uSv':1}, {'dose_rate_uSv_h':0.1}):
            with self.subTest(data=data), self.assertRaises(ProcessingError):
                process_packet(self.pkt(**data))

    def test_require_basis_and_source(self):
        with self.assertRaises(ProcessingError):
            process_packet(self.pkt(solar_event_dose=1, radiation_source='spe'))
        with self.assertRaises(ProcessingError):
            process_packet(self.pkt(solar_event_dose=1, radiation_source='gcr', measurement_basis='nasa_effective_dose_model'))
        with self.assertRaises(ProcessingError):
            process_packet(self.pkt(sensor='radiation_environment', daily_gcr_dose_rate=0.3,
                radiation_source='gcr', environment='unspecified', measurement_basis='nasa_effective_dose_model'))

    def test_valid_separate_quantities(self):
        data={'radiation_source':'spe','measurement_basis':'nasa_effective_dose_model','solar_event_dose':2}
        self.assertEqual(process_packet(self.pkt(**data)).reading.measurements[0].unit, 'mSv')
        data={'radiation_source':'gcr','environment':'free_space','measurement_basis':'nasa_effective_dose_model','daily_gcr_dose_rate':0.3}
        self.assertEqual(process_packet(self.pkt('radiation_environment',**data)).reading.measurements[0].unit, 'mSv/day')

if __name__=='__main__': unittest.main()
