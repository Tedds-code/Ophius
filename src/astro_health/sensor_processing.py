# Made in cooperation with ChatGPT
# File: src/astro_health/sensor_processing.py
"""Convert standardized sensor packets to fixed, numeric Reading values.

Signal algorithms here are deterministic educational demonstrations, tested
on synthetic signals. They are NOT validated for clinical measurements.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from pathlib import Path

from astro_health.models import MeasurementValue, Reading
from astro_health.fixed_tests import FIELDS_BY_MEASUREMENT
from astro_health.sensor_packets import SensorPacket
from astro_health.thermistor_sensor import ThermistorConfig, adc_to_celsius


class ProcessingError(ValueError):
    """A packet cannot be interpreted without unsafe assumptions."""


@dataclass(frozen=True)
class ProcessedPacket:
    reading: Reading
    notes: tuple[str, ...] = ()


def _number(data, key: str, *, minimum=None, maximum=None) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProcessingError(f"{key} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ProcessingError(f"{key} must be finite")
    if minimum is not None and number < minimum:
        raise ProcessingError(f"{key} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ProcessingError(f"{key} must be <= {maximum}")
    return number


def _series(data, key: str, *, minimum_length=1) -> list[float]:
    values = data.get(key)
    if not isinstance(values, list) or len(values) < minimum_length:
        raise ProcessingError(f"{key} must be a list with >= {minimum_length} samples")
    return [_number({key: value}, key) for value in values]


def _metric(name: str, value: float, unit: str) -> MeasurementValue:
    if not math.isfinite(value):
        raise ProcessingError(f"Calculated {name} is not finite")
    return MeasurementValue(name, float(value), unit)


def _window_peaks(samples: list[float], sample_rate_hz: float) -> list[int]:
    """Simple local-max detector for CLEAN synthetic waves ONLY.

    Minimum separation is an engineering parameter, not a medical limit.
    Motion artifacts, noise, ectopic beats and real physiology require a
    separate, validated detection pipeline and signal-quality controls.
    """
    if len(samples) < 10 or sample_rate_hz <= 0:
        raise ProcessingError("Insufficient waveform samples")
    amplitude = max(samples) - min(samples)
    if amplitude <= 1e-9:
        raise ProcessingError("Waveform is flat; no pulses can be extracted")
    low = min(samples) + amplitude * 0.6
    separation = max(1, round(0.30 * sample_rate_hz))
    peaks = []
    for i in range(1, len(samples) - 1):
        if samples[i] > samples[i - 1] and samples[i] >= samples[i + 1] and samples[i] >= low:
            if peaks and i - peaks[-1] < separation:
                if samples[i] > samples[peaks[-1]]:
                    peaks[-1] = i
            else:
                peaks.append(i)
    if len(peaks) < 2:
        raise ProcessingError("Too few identifiable peaks in waveform")
    return peaks


def _pulse_metrics(data: dict, channel: str, hr_name: str, hrv_name: str):
    samples = _series(data, channel, minimum_length=10)
    fs = _number(data, "sample_rate_hz", minimum=0.01)
    peaks = _window_peaks(samples, fs)
    intervals = [(b - a) / fs for a, b in zip(peaks, peaks[1:])]
    # These are signal features, not a validated physiological assessment.
    measurements = [_metric(hr_name, 60 / statistics.mean(intervals), "bpm")]
    if len(intervals) >= 2:
        delta_ms = [(b - a) * 1000 for a, b in zip(intervals, intervals[1:])]
        rmssd = math.sqrt(statistics.mean(x * x for x in delta_ms))
        measurements.append(_metric(hrv_name, rmssd, "ms"))
    return measurements


def _mean_axis(data: dict, channel: str) -> float:
    value = data.get(channel)
    if isinstance(value, list):
        return statistics.mean(_series(data, channel))
    return _number(data, channel)


def process_packet(
    packet: SensorPacket,
    *,
    thermistor_config: ThermistorConfig | None = None,
    image_root: Path | None = None,
) -> ProcessedPacket:
    """Convert an incoming packet to a Reading without medical evaluation.

    Processed numerical values go into SQLite; raw samples go into a separate
    JSONL log through SensorRecorder. Image files are never embedded in SQLite.
    """
    data = packet.data
    measurements: list[MeasurementValue] = []
    notes = []

    if packet.sensor == "thermistor":
        if "adc_count" in data:
            adc = data["adc_count"]
            if isinstance(adc, bool) or not isinstance(adc, int):
                raise ProcessingError("adc_count must be an integer")
            try:
                temp = adc_to_celsius(adc, thermistor_config or ThermistorConfig())
            except ValueError as exc:
                raise ProcessingError(str(exc)) from exc
            notes.append("NTC beta conversion uses configured electrical parameters; not clinical calibration")
        else:
            temp = _number(data, "temperature_c")
            notes.append("Device-reported skin temperature; device calibration is not independently verified")
        measurements.append(_metric("skin_temperature", temp, "degC"))

    elif packet.sensor == "imu":
        axes = ("x", "y", "z")
        # Windowed axes must stay aligned sample-for-sample.
        accel_keys = [f"a{axis}_m_s2" for axis in axes]
        axis_values = [data.get(key) for key in accel_keys]
        if any(isinstance(value, list) for value in axis_values):
            if not all(isinstance(value, list) for value in axis_values):
                raise ProcessingError("Windowed acceleration requires three sample lists")
            if len({len(value) for value in axis_values}) != 1:
                raise ProcessingError("Acceleration axes have mismatched sample counts")
        has_gyro = any(f"g{axis}_dps" in data for axis in axes)
        for axis in axes:
            measurements.append(_metric(f"acceleration_{axis}", _mean_axis(data, f"a{axis}_m_s2"), "m/s^2"))
        if has_gyro:
            if not all(f"g{axis}_dps" in data for axis in axes):
                raise ProcessingError("Gyroscope needs all three axes")
            for axis in axes:
                measurements.append(_metric(f"angular_velocity_{axis}", _mean_axis(data, f"g{axis}_dps"), "deg/s"))
        notes.append("No step count or sleep-stage inference")

    elif packet.sensor == "ppg":
        if "ir_samples" in data:
            measurements.extend(_pulse_metrics(data, "ir_samples", "heart_rate", "hrv_rmssd"))
            if "red_samples" in data:
                red = _series(data, "red_samples", minimum_length=10)
                if len(red) != len(data["ir_samples"]):
                    raise ProcessingError("Red and IR sample lengths must match")
            notes.append("Waveform HR/HRV is a synthetic-signal demonstration, NOT clinically validated")
        elif "heart_rate_bpm" in data:
            measurements.append(_metric("heart_rate", _number(data, "heart_rate_bpm", minimum=0), "bpm"))
            notes.append("Device-reported HR; no independent validation")
        if "spo2_percent" in data:
            if not packet.calibration_id:
                raise ProcessingError("SpO2 requires calibration_id and a device-derived value")
            measurements.append(_metric("spo2", _number(data, "spo2_percent", minimum=0, maximum=100), "%"))
            notes.append("Device-reported SpO2; calibration identifier is metadata, not proof of accuracy")
        if not measurements:
            raise ProcessingError("PPG needs IR waveform, device HR or calibrated device SpO2")

    elif packet.sensor == "ecg":
        if "ecg_samples" in data:
            measurements.extend(_pulse_metrics(data, "ecg_samples", "ecg_heart_rate", "ecg_hrv_rmssd"))
            notes.append("R-peak extraction is demonstrative; no arrhythmia diagnosis")
        else:
            measurements.append(_metric("ecg_heart_rate", _number(data, "heart_rate_bpm", minimum=0), "bpm"))
            notes.append("Device-reported ECG heart rate; no waveform diagnosis")
        if "qtc_ms" in data:
            measurements.append(_metric("qtc_interval", _number(data, "qtc_ms", minimum=0), "ms"))
            notes.append("Device-reported QTc; waveform algorithm does not derive this value")

    elif packet.sensor == "blood_pressure":
        systolic = _number(data, "blood_pressure_systolic", minimum=0)
        diastolic = _number(data, "blood_pressure_diastolic", minimum=0)
        if systolic <= diastolic:
            raise ProcessingError("Systolic pressure must be above diastolic pressure")
        measurements.append(_metric("blood_pressure_systolic", systolic, "mmHg"))
        measurements.append(_metric("blood_pressure_diastolic", diastolic, "mmHg"))
        notes.append("Device-reported cuff BP; physical device calibration must be validated")

    elif packet.sensor == "eda":
        measurements.append(_metric("skin_conductance", _number(data, "conductance_us", minimum=0), "uS"))
        notes.append("Skin conductance is not itself a stress diagnosis")

    elif packet.sensor in ("radiation", "radiation_environment"):
        from astro_health.radiation import radiation_specification, NASA_MEASUREMENT_FIELDS
        spec = radiation_specification(packet)
        for channel, (name, unit) in NASA_MEASUREMENT_FIELDS.items():
            if channel in data:
                measurements.append(_metric(name, _number(data, channel, minimum=0), unit))
        notes.append(
            f"Monitor: {packet.sensor}; radiation source: {spec.radiation_source}; "
            f"environment: {spec.environment}; basis: {spec.measurement_basis}"
        )
        notes.append("Externally established dose quantities; no dose inferred from raw counts")

    elif packet.sensor == "co2":
        if "co2_1h_mmhg" in data:
            minutes = _number(data, "sample_period_minutes", minimum=60)
            if minutes != 60:
                raise ProcessingError("JSON cabin_co2 rule specifies exactly a one-hour average")
            measurements.append(_metric("cabin_co2", _number(data, "co2_1h_mmhg", minimum=0), "mmHg"))
            notes.append("Device-reported one-hour partial-pressure average; validate instrument provenance")
        if "co2_ppm" in data:
            measurements.append(_metric("co2_concentration", _number(data, "co2_ppm", minimum=0), "ppm"))
            notes.append("Device spot ppm is not the uploaded JSON one-hour mmHg rule")
        if not measurements:
            raise ProcessingError("CO2 requires an hourly partial pressure or reported ppm")

    elif packet.sensor == "noise":
        if "sound_level_dba" in data:
            measurements.append(_metric("sound_level", _number(data, "sound_level_dba"), "dBA"))
            notes.append("dBA must be supplied by a calibrated sound-level device")
        elif "audio_samples" in data:
            audio = _series(data, "audio_samples")
            rms = math.sqrt(statistics.mean(x * x for x in audio))
            measurements.append(_metric("audio_relative_rms", rms, "relative"))
            notes.append("Relative RMS is NOT dBA without microphone calibration and frequency weighting")
        else:
            raise ProcessingError("Noise device needs sound_level_dba or audio_samples")

    elif packet.sensor == "bioimpedance":
        measurements.append(_metric("bioimpedance", _number(data, "impedance_ohms", minimum=0), "ohm"))
        notes.append("Impedance alone does not establish fat or muscle mass")

    elif packet.sensor == "eye_imaging":
        if image_root is None:
            raise ProcessingError("eye_imaging requires an image_root directory")
        image_name = data.get("image_path")
        if not isinstance(image_name, str) or Path(image_name).is_absolute():
            raise ProcessingError("image_path must be relative to image_root")
        root = Path(image_root).resolve()
        image = (root / image_name).resolve()
        if not image.is_relative_to(root) or image.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp"):
            raise ProcessingError("Image path must be an allowed file beneath image_root")
        if not image.is_file() or image.stat().st_size <= 0:
            raise ProcessingError("Eye image does not exist or is empty")
        measurements.append(_metric("eye_image_captured", 1, "count"))
        notes.append("Image reference only; no SANS or eye-health assessment")

    else:
        raise ProcessingError(f"Unhandled sensor: {packet.sensor}")

    # Enforce the fixed catalog: devices cannot invent measurement labels/units.
    for measurement in measurements:
        field = FIELDS_BY_MEASUREMENT.get(measurement.measurement_type)
        if field is None or field.unit != measurement.unit:
            raise ProcessingError("Processed measurement is not in the fixed catalog")

    return ProcessedPacket(
        reading=Reading(
            source=f"{packet.origin}_{packet.sensor}",
            measurements=tuple(measurements),
            timestamp=packet.timestamp,
        ),
        notes=tuple(notes),
    )
