# Made in cooperation with ChatGPT
# File: tests/test_sensor_processing.py

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from astro_health.sensor_packets import SensorPacket
from astro_health.sensor_processing import ProcessingError, process_packet
from astro_health.sensor_simulators import make_simulated_packet


class TestSensorProcessing(unittest.TestCase):
    def setUp(self):
        self.date = datetime(2026, 11, 11, tzinfo=timezone.utc)

    def packet(self, sensor, data, **more):
        return SensorPacket(sensor, self.date, data, **more)

    def names(self, result):
        return {m.measurement_type: m for m in result.reading.measurements}

    def test_thermistor_adc_and_direct_reading(self):
        result = process_packet(self.packet("thermistor", {"adc_count": 2048}))
        self.assertAlmostEqual(self.names(result)["skin_temperature"].value, 25, delta=0.1)
        direct = process_packet(self.packet("thermistor", {"temperature_c": 33.5}))
        self.assertEqual(self.names(direct)["skin_temperature"].unit, "degC")
        self.assertEqual(self.names(direct)["skin_temperature"].value, 33.5)

    def test_thermistor_rejects_saturation(self):
        with self.assertRaises(ProcessingError):
            process_packet(self.packet("thermistor", {"adc_count": 0}))

    def test_imu_single_and_window_averages(self):
        result = process_packet(self.packet("imu", {
            "ax_m_s2": [0, 2], "ay_m_s2": [1, 3], "az_m_s2": [9, 11],
            "gx_dps": 1, "gy_dps": 2, "gz_dps": 3,
        }))
        values = self.names(result)
        self.assertEqual(values["acceleration_x"].value, 1)
        self.assertEqual(values["acceleration_y"].value, 2)
        self.assertEqual(values["angular_velocity_z"].value, 3)

    def test_imu_requires_all_acceleration_axes(self):
        with self.assertRaises(ProcessingError):
            process_packet(self.packet("imu", {"ax_m_s2": 0, "az_m_s2": 9}))

    def test_ppg_synthetic_waveform_rate_and_hrv(self):
        p = make_simulated_packet("ppg", timestamp=self.date)
        result = process_packet(p)
        values = self.names(result)
        self.assertAlmostEqual(values["heart_rate"].value, 72, delta=2)
        self.assertIn("hrv_rmssd", values)
        self.assertEqual(values["heart_rate"].unit, "bpm")
        self.assertNotIn("spo2", values)
        self.assertEqual(result.reading.quality, "unassessed")

    def test_ppg_rejects_flat_wave(self):
        with self.assertRaises(ProcessingError):
            process_packet(self.packet("ppg", {
                "ir_samples": [5] * 100, "sample_rate_hz": 50,
            }))

    def test_spo2_requires_calibration_identifier(self):
        with self.assertRaises(ProcessingError):
            process_packet(self.packet("ppg", {"spo2_percent": 97.0}))
        result = process_packet(self.packet(
            "ppg", {"spo2_percent": 97.0}, calibration_id="vendor-2026",
        ))
        self.assertEqual(self.names(result)["spo2"].value, 97.0)
        self.assertEqual(result.reading.quality, "unassessed")
        with self.assertRaises(ProcessingError):
            process_packet(self.packet("ppg", {"spo2_percent": 120}, calibration_id="v1"))

    def test_ecg_synthetic_heart_rate(self):
        result = process_packet(make_simulated_packet("ecg", timestamp=self.date))
        self.assertAlmostEqual(self.names(result)["ecg_heart_rate"].value, 72, delta=2)
        self.assertIn("ecg_hrv_rmssd", self.names(result))
        self.assertNotIn("arrhythmia", self.names(result))

    def test_eda(self):
        result = process_packet(self.packet("eda", {"conductance_us": 4.5}))
        self.assertEqual(self.names(result)["skin_conductance"].unit, "uS")

    def test_radiation_requires_nasa_aligned_quantity(self):
        for data in ({"counts": 4}, {"dose_uSv": 0.5},
                     {"dose_rate_uSv_h": 0.1}, {"particle_type": "gamma"}):
            with self.subTest(data=data), self.assertRaises(ProcessingError):
                process_packet(self.packet("radiation", data))
        result = process_packet(self.packet("radiation", {
            "radiation_source": "spe",
            "measurement_basis": "nasa_effective_dose_model",
            "solar_event_dose": 0.5,
        }))
        self.assertEqual(self.names(result)["spe_effective_dose"].unit, "mSv")

    def test_co2(self):
        result = process_packet(self.packet("co2", {"co2_ppm": 640}))
        self.assertEqual(self.names(result)["co2_concentration"].unit, "ppm")

    def test_noise_relative_rms_is_not_dba(self):
        raw = process_packet(self.packet("noise", {"audio_samples": [-0.2, 0.2]}))
        self.assertAlmostEqual(self.names(raw)["audio_relative_rms"].value, 0.2)
        self.assertNotIn("sound_level", self.names(raw))
        level = process_packet(self.packet("noise", {"sound_level_dba": 50.2}))
        self.assertEqual(self.names(level)["sound_level"].unit, "dBA")

    def test_bioimpedance_does_not_infer_body_composition(self):
        result = process_packet(self.packet("bioimpedance", {"impedance_ohms": 510}))
        self.assertEqual(set(self.names(result)), {"bioimpedance"})

    def test_eye_image_requires_local_file_and_safe_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "capture.png").write_bytes(b"real file placeholder")
            result = process_packet(self.packet(
                "eye_imaging", {"image_path": "capture.png"}
            ), image_root=root)
            self.assertEqual(self.names(result)["eye_image_captured"].value, 1)
            with self.assertRaises(ProcessingError):
                process_packet(self.packet(
                    "eye_imaging", {"image_path": "../escape.png"}
                ), image_root=root)
            with self.assertRaises(ProcessingError):
                process_packet(self.packet(
                    "eye_imaging", {"image_path": "missing.png"}
                ), image_root=root)

    def test_reject_unavailable_eda_adc_conversion(self):
        with self.assertRaises(ProcessingError):
            process_packet(self.packet("eda", {"adc_count": 2000}))


if __name__ == "__main__":
    unittest.main()
