# Made in cooperation with ChatGPT
# File: src/astro_health/sensor_simulators.py
"""Repeatable, synthetic packets for all proposed sensor categories.

No values represent an astronaut. These are engineering test fixtures, not
validated clinical signals and not reference/normal values.
"""

from __future__ import annotations

import base64
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from astro_health.sensor_packets import SENSOR_TYPES, SensorPacket
from astro_health.thermistor_sensor import ThermistorConfig, simulate_adc

# A legitimate 1x1 PNG, used only to demonstrate image-file referencing.
# It is not an image of an eye and must never be analyzed as one.
_DEMO_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Y9rvWQAAAAASUVORK5CYII="
)


def _waveform(kind: str, index: int) -> dict:
    fs = 50 if kind == "ppg" else 100
    duration_s = 12
    frequency_hz = 1.2
    count = duration_s * fs
    if kind == "ppg":
        ir = [1000 + 90 * math.cos(2 * math.pi * frequency_hz * n / fs)
              for n in range(count)]
        red = [900 + 40 * math.cos(2 * math.pi * frequency_hz * n / fs)
               for n in range(count)]
        return {"sample_rate_hz": fs, "ir_samples": ir, "red_samples": red}
    # Gaussian spikes, a convenient synthetic peak-detection fixture.
    # Not intended to resemble a medically plausible ECG morphology.
    return {
        "sample_rate_hz": fs,
        "ecg_samples": [
            math.exp(-((n / fs * frequency_hz % 1 - 0.5) / 0.055) ** 2)
            for n in range(count)
        ],
    }


def make_simulated_packet(
    sensor: str,
    index: int = 0,
    *,
    timestamp: datetime | None = None,
    image_root: Path | None = None,
) -> SensorPacket:
    """Create a deterministic packet; each sensor uses its expected fields."""
    if sensor not in SENSOR_TYPES:
        raise ValueError(f"Unknown sensor: {sensor}")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("index must be a nonnegative integer")
    timestamp = timestamp or datetime.now(timezone.utc)

    if sensor == "thermistor":
        data = {"adc_count": simulate_adc(31 + 0.2 * math.sin(index / 5), ThermistorConfig())}
    elif sensor == "ppg":
        data = {**_waveform("ppg", index), "spo2_percent": 98.0 - (index % 3) * 0.2}
    elif sensor == "imu":
        data = {
            "ax_m_s2": 0.1 * math.sin(index / 4),
            "ay_m_s2": 0.1 * math.cos(index / 4),
            "az_m_s2": 9.81,
            "gx_dps": 0.1, "gy_dps": 0.2, "gz_dps": 0.3,
        }
    elif sensor == "ecg":
        data = {**_waveform("ecg", index), "qtc_ms": 420.0 + (index % 4)}
    elif sensor == "blood_pressure":
        data = {"blood_pressure_systolic": 115 + (index % 4),
                "blood_pressure_diastolic": 74 + (index % 3)}
    elif sensor == "eda":
        data = {"conductance_us": 4.0 + 0.1 * math.sin(index / 4)}
    elif sensor == "radiation":
        # These are independent snapshot examples, NOT independently measured
        # astronaut doses or medically validated physical simulations.
        cases = (
            {'radiation_source': 'other', 'cumulative_effective_dose': 1.0},
            {'radiation_source': 'spe', 'solar_event_dose': 0.5},
            {'radiation_source': 'nuclear_technology', 'nuclear_source_dose': 0.2},
            {'radiation_source': 'other', 'lens_dose': 0.1,
             'skin_dose': 0.15, 'bfo_dose': 0.12},
        )
        data = {
            'measurement_basis': 'nasa_effective_dose_model',
            **cases[index % len(cases)],
        }
    elif sensor == "radiation_environment":
        # Synthetic NASA-aligned habitat environment example, not a real
        # detector reading or an inferred biological dose.
        environments = ('free_space', 'planetary_surface')
        data = {
            'radiation_source': 'gcr',
            'environment': environments[index % len(environments)],
            'measurement_basis': 'nasa_effective_dose_model',
            'daily_gcr_dose_rate': 0.3 + 0.01 * (index % 3),
        }
    elif sensor == "co2":
        data = {"co2_ppm": 600 + index % 10, "co2_1h_mmhg": 2.0, "sample_period_minutes": 60}
    elif sensor == "noise":
        data = {"sound_level_dba": 45.0 + index % 3}
    elif sensor == "bioimpedance":
        data = {"impedance_ohms": 510.0 + index % 4}
    elif sensor == "eye_imaging":
        if image_root is None:
            raise ValueError("eye_imaging simulation requires image_root")
        root = Path(image_root)
        root.mkdir(parents=True, exist_ok=True)
        name = f"simulated_eye_placeholder_{index:06d}.png"
        (root / name).write_bytes(base64.b64decode(_DEMO_PNG))
        data = {"image_path": name}
    else:
        raise ValueError(sensor)

    return SensorPacket(
        sensor=sensor, timestamp=timestamp, data=data,
        origin="simulated", device_id=f"virtual_{sensor}",
        calibration_id="SYNTHETIC_ONLY" if sensor == "ppg" else None,
    )


def simulated_stream(
    sensor: str,
    *,
    count: int | None = 10,
    interval_seconds: float = 1.0,
    realtime: bool = False,
    image_root: Path | None = None,
) -> Iterator[SensorPacket]:
    """Yield finite packets, or continuously until interrupted if count=None.

    realtime=False: time advances in packet timestamps, no wall-clock delay.
    realtime=True: delays between packet reports, then uses actual UTC time.
    Each PPG/ECG packet holds one illustrative 12-second waveform window.
    """
    if count is not None and (
        isinstance(count, bool) or not isinstance(count, int) or count <= 0
    ):
        raise ValueError("count must be positive or None")
    if (isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or not math.isfinite(interval_seconds) or interval_seconds <= 0):
        raise ValueError("interval_seconds must be positive and finite")
    start = datetime.now(timezone.utc)
    n = 0
    while count is None or n < count:
        if realtime and n > 0:
            time.sleep(interval_seconds)
        timestamp = (datetime.now(timezone.utc) if realtime
                     else start + timedelta(seconds=n * interval_seconds))
        yield make_simulated_packet(
            sensor, n, timestamp=timestamp, image_root=image_root,
        )
        n += 1
