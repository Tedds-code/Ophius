# Made in cooperation with ChatGPT
# File: tests/test_sensor_simulators.py

import itertools
import tempfile
import unittest
from pathlib import Path

from astro_health.fixed_tests import FIELDS_BY_MEASUREMENT, MANUAL_TESTS
from astro_health.sensor_packets import SENSOR_TYPES
from astro_health.sensor_processing import process_packet
from astro_health.sensor_simulators import make_simulated_packet, simulated_stream


class TestSensorSimulators(unittest.TestCase):
    def test_every_sensor_has_a_simulator_and_fixed_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            image_root = Path(temp)
            for sensor in SENSOR_TYPES:
                with self.subTest(sensor=sensor):
                    p = make_simulated_packet(sensor, image_root=image_root)
                    result = process_packet(p, image_root=image_root)
                    self.assertGreater(len(result.reading.measurements), 0)
                    self.assertEqual(result.reading.source, f"simulated_{sensor}")
                    self.assertEqual(result.reading.quality, "unassessed")
                    for metric in result.reading.measurements:
                        self.assertEqual(
                            metric.unit, FIELDS_BY_MEASUREMENT[metric.measurement_type].unit
                        )

    def test_continuous_stream_can_be_safely_sliced(self):
        stream = simulated_stream("imu", count=None, interval_seconds=2)
        packets = list(itertools.islice(stream, 3))
        self.assertEqual(len(packets), 3)
        self.assertEqual((packets[2].timestamp - packets[0].timestamp).total_seconds(), 4)

    def test_invalid_arguments_fail_early(self):
        with self.assertRaises(ValueError):
            list(simulated_stream("eda", count=0))
        with self.assertRaises(ValueError):
            list(simulated_stream("eda", interval_seconds=0))

    def test_catalog_is_fixed_and_eye_capture_sensor_only(self):
        self.assertNotIn("eye_image_captured", {t.test_id for t in MANUAL_TESTS})
        self.assertIn("bioimpedance", FIELDS_BY_MEASUREMENT)
        self.assertIn("co2_concentration", FIELDS_BY_MEASUREMENT)


if __name__ == "__main__":
    unittest.main()
