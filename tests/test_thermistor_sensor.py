# Made in cooperation with ChatGPT
# File: tests/test_thermistor_sensor.py

import unittest

from astro_health.thermistor_sensor import (
    SimulatedThermistorSource,
    ThermistorConfig,
    adc_to_celsius,
    simulate_adc,
)


class TestThermistorSensor(unittest.TestCase):

    def setUp(self):
        self.config = ThermistorConfig()

    def test_25c_is_near_adc_midpoint(self):
        adc = simulate_adc(25.0, self.config)
        self.assertAlmostEqual(adc, self.config.adc_max / 2, delta=1)
        self.assertAlmostEqual(
            adc_to_celsius(adc, self.config), 25.0, delta=0.05
        )

    def test_conversion_round_trip_at_several_temperatures(self):
        # Checks arithmetic + ADC quantization for illustrative parameters.
        for expected in (20.0, 25.0, 30.0, 35.0):
            with self.subTest(expected=expected):
                adc = simulate_adc(expected, self.config)
                actual = adc_to_celsius(adc, self.config)
                self.assertAlmostEqual(actual, expected, delta=0.05)

    def test_saturated_adc_values_are_rejected(self):
        for value in (0, self.config.adc_max, -1, self.config.adc_max + 1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    adc_to_celsius(value, self.config)

    def test_invalid_config_rejected(self):
        with self.assertRaises(ValueError):
            ThermistorConfig(beta_kelvin=0)

    def test_stream_produces_fixed_labels_and_timestamps(self):
        samples = list(
            SimulatedThermistorSource().stream(
                sample_count=4,
                interval_seconds=2.0,
            )
        )
        self.assertEqual(len(samples), 4)

        for raw, reading in samples:
            self.assertEqual(raw.timestamp, reading.timestamp)
            self.assertEqual(reading.source, "simulated_thermistor")
            self.assertEqual(reading.quality, "unassessed")
            self.assertEqual(reading.measurements[0].measurement_type, "skin_temperature")
            self.assertEqual(reading.measurements[0].unit, "degC")

        self.assertEqual(
            (samples[1][0].timestamp - samples[0][0].timestamp).total_seconds(),
            2.0,
        )

    def test_read_returns_reading(self):
        reading = SimulatedThermistorSource().read()
        self.assertEqual(reading.measurements[0].measurement_type, "skin_temperature")

    def test_indefinite_stream_can_be_stopped_by_caller(self):
        import itertools

        sensor = SimulatedThermistorSource()
        first_three = list(itertools.islice(sensor.stream(), 3))
        self.assertEqual(len(first_three), 3)

    def test_bad_stream_arguments_are_rejected(self):
        sensor = SimulatedThermistorSource()
        with self.assertRaises(ValueError):
            list(sensor.stream(0))
        with self.assertRaises(ValueError):
            list(sensor.stream(1, interval_seconds=0))


if __name__ == "__main__":
    unittest.main()
