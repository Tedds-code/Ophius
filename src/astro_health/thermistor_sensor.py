# Made in cooperation with ChatGPT
# File: src/astro_health/thermistor_sensor.py

import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from astro_health.fixed_tests import TESTS_BY_ID
from astro_health.models import MeasurementValue, Reading
from astro_health.reading_source import ReadingSource


@dataclass(frozen=True)
class ThermistorConfig:
    """Illustrative NTC voltage-divider parameters, not calibration data."""

    resistance_at_25c_ohms: float = 10_000.0
    beta_kelvin: float = 3950.0
    fixed_resistor_ohms: float = 10_000.0
    adc_max: int = 4095  # 12-bit ADC, from 0 to 4095 inclusive

    def __post_init__(self):
        for value in (
            self.resistance_at_25c_ohms,
            self.beta_kelvin,
            self.fixed_resistor_ohms,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Thermistor parameters must be positive and finite.")
        if isinstance(self.adc_max, bool) or not isinstance(self.adc_max, int):
            raise ValueError("adc_max must be an integer.")
        if self.adc_max < 3:
            raise ValueError("adc_max is too small.")


@dataclass(frozen=True)
class RawThermistorSample:
    """One ADC reading from a simulated thermistor interface."""

    timestamp: datetime
    adc_count: int


def adc_to_celsius(adc_count: int, config: ThermistorConfig) -> float:
    """Convert ADC count to temperature for the specified divider wiring.

    Assumes the thermistor is connected to supply voltage, a fixed
    resistor is connected to ground, and the ADC measures their junction.
    The ADC reference is assumed equal to the divider supply voltage.

    For this arrangement the divider is reversed relative to a
    thermistor-to-ground circuit, so a larger ADC count means a higher
    temperature. Follow the exact wiring description in the docstring.
    """
    if isinstance(adc_count, bool) or not isinstance(adc_count, int):
        raise ValueError("ADC count must be an integer.")
    if not 0 < adc_count < config.adc_max:
        raise ValueError("ADC reading is saturated or outside the valid range.")

    # Supply -> thermistor -> ADC junction -> fixed resistor -> ground.
    # Vout/Vsupply = R_fixed / (R_thermistor + R_fixed).
    resistance = config.fixed_resistor_ohms * (
        config.adc_max - adc_count
    ) / adc_count

    inverse_kelvin = (
        1.0 / 298.15
        + math.log(resistance / config.resistance_at_25c_ohms)
        / config.beta_kelvin
    )
    if inverse_kelvin <= 0:
        raise ValueError("Thermistor conversion is outside the model range.")
    return 1.0 / inverse_kelvin - 273.15


def simulate_adc(temperature_c: float, config: ThermistorConfig) -> int:
    """Simulate ADC output from a known synthetic temperature."""
    if not isinstance(temperature_c, (int, float)) or isinstance(temperature_c, bool):
        raise ValueError("Synthetic temperature must be a number.")
    if not math.isfinite(temperature_c) or temperature_c <= -273.15:
        raise ValueError("Synthetic temperature is invalid.")

    kelvin = temperature_c + 273.15
    resistance = config.resistance_at_25c_ohms * math.exp(
        config.beta_kelvin * (1.0 / kelvin - 1.0 / 298.15)
    )
    adc = round(
        config.adc_max * config.fixed_resistor_ohms
        / (resistance + config.fixed_resistor_ohms)
    )
    if not 0 < adc < config.adc_max:
        raise ValueError("Synthetic signal saturates the ADC.")
    return adc


class SimulatedThermistorSource(ReadingSource):
    """Generate repeatable synthetic ADC samples and processed readings.

    stream() can run in real time or in accelerated simulation mode.
    """

    def __init__(self, config: ThermistorConfig | None = None):
        self.config = config or ThermistorConfig()
        self._index = 0

    def _next_sample(self, timestamp: datetime) -> tuple[RawThermistorSample, Reading]:
        # Arbitrary synthetic waveform; NOT an astronaut's actual temperature.
        synthetic_temperature_c = 31.0 + 0.5 * math.sin(self._index / 5.0)
        self._index += 1

        raw = RawThermistorSample(
            timestamp=timestamp,
            adc_count=simulate_adc(synthetic_temperature_c, self.config),
        )
        processed_temperature = adc_to_celsius(raw.adc_count, self.config)
        field = TESTS_BY_ID["skin_temperature"].fields[0]
        reading = Reading(
            source="simulated_thermistor",
            timestamp=timestamp,
            measurements=(
                MeasurementValue(
                    measurement_type=field.measurement_type,
                    value=processed_temperature,
                    unit=field.unit,
                ),
            ),
        )
        return raw, reading

    def read(self) -> Reading:
        """Provide one processed reading through the ReadingSource interface."""
        _, reading = self._next_sample(datetime.now(timezone.utc))
        return reading

    def stream(
        self,
        sample_count: int | None = None,
        interval_seconds: float = 1.0,
        realtime: bool = False,
    ):
        """Yield raw and processed samples; None means until interrupted.

        realtime=False is an accelerated test mode with simulated timestamps.
        realtime=True waits between samples and uses the real clock.
        """
        if sample_count is not None and (
            isinstance(sample_count, bool)
            or not isinstance(sample_count, int)
            or sample_count <= 0
        ):
            raise ValueError("sample_count must be a positive integer or None.")
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or not math.isfinite(interval_seconds)
            or interval_seconds <= 0
        ):
            raise ValueError("interval_seconds must be positive and finite.")

        start = datetime.now(timezone.utc)
        index = 0
        while sample_count is None or index < sample_count:
            if realtime and index > 0:
                time.sleep(interval_seconds)
            timestamp = (
                datetime.now(timezone.utc)
                if realtime
                else start + timedelta(seconds=index * interval_seconds)
            )
            yield self._next_sample(timestamp)
            index += 1
