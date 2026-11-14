# Made in cooperation with ChatGPT
# File: tests/test_sensor_packets.py

import unittest
from datetime import datetime, timezone

from astro_health.sensor_packets import PacketError, SensorPacket


class TestSensorPackets(unittest.TestCase):
    def make_packet(self, **changes):
        d = {
            "sensor": "imu",
            "timestamp": "2026-11-11T14:30:00Z",
            "data": {"ax_m_s2": 1.0, "ay_m_s2": 2.0, "az_m_s2": 3.0},
        }
        d.update(changes)
        return SensorPacket.from_dict(d)

    def test_roundtrip_json_and_utc(self):
        first = self.make_packet()
        second = SensorPacket.from_json(first.to_json())
        self.assertEqual(first, second)
        self.assertEqual(second.timestamp.utcoffset().total_seconds(), 0)

    def test_timezone_aware_required(self):
        with self.assertRaises(PacketError):
            self.make_packet(timestamp="2026-11-11T14:30:00")

    def test_unknown_sensor_rejected(self):
        with self.assertRaises(PacketError):
            self.make_packet(sensor="telepathy")

    def test_nonfinite_and_boolean_values_rejected(self):
        for value in (float("nan"), float("inf"), True, [0.1, float("nan")], []):
            with self.subTest(value=value), self.assertRaises(PacketError):
                self.make_packet(data={"ax_m_s2": value})

    def test_samples_limit(self):
        with self.assertRaises(PacketError):
            self.make_packet(data={"waveform": [0.0] * 20001})

    def test_extra_fields_rejected(self):
        with self.assertRaises(PacketError):
            self.make_packet(secret_field=10)

    def test_invalid_json_and_large_packets_rejected(self):
        with self.assertRaises(PacketError):
            SensorPacket.from_json("not json")
        with self.assertRaises(PacketError):
            SensorPacket.from_json(" " * 2_000_001)

    def test_device_provenance_preserved(self):
        p = self.make_packet(origin="replay", device_id="device_a", calibration_id="cal-v1")
        self.assertEqual(p.origin, "replay")
        self.assertEqual(p.device_id, "device_a")
        self.assertEqual(p.calibration_id, "cal-v1")

    def test_utc_timestamp_manual_creation(self):
        p = SensorPacket("co2", datetime.now(timezone.utc), {"co2_ppm": 450})
        self.assertEqual(p.sensor, "co2")


if __name__ == "__main__":
    unittest.main()
