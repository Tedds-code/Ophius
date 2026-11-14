# Made in cooperation with ChatGPT
# File: src/astro_health/fixed_tests.py
"""Stable, PRELIMINARY measurement/test catalog; no medical limits.

All automated sensor measurements are assigned to one of these fixed fields.
The astronaut can select from the manual-capable tests, not invent field
names or units. Hardware integrations must not let a device choose labels.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TestField:
    measurement_type: str
    display_name: str
    unit: str


@dataclass(frozen=True)
class FixedTest:
    test_id: str
    display_name: str
    fields: tuple[TestField, ...]
    sensor_type: str | None = None
    manual_enabled: bool = True


FIXED_TESTS: tuple[FixedTest, ...] = (
    FixedTest("skin_temperature", "Skin temperature", (
        TestField("skin_temperature", "Skin temperature", "degC"),), "thermistor"),
    FixedTest("heart_rate", "Heart rate", (
        TestField("heart_rate", "Heart rate", "bpm"),), "ppg"),
    FixedTest("hrv_rmssd", "Heart-rate variability (RMSSD)", (
        TestField("hrv_rmssd", "HRV (RMSSD)", "ms"),), "ppg"),
    FixedTest("spo2", "Blood oxygen saturation", (
        TestField("spo2", "SpO2", "%"),), "ppg"),
    FixedTest("blood_pressure", "Blood pressure (manual)", (
        TestField("systolic_pressure", "Systolic pressure", "mmHg"),
        TestField("diastolic_pressure", "Diastolic pressure", "mmHg"))),
    FixedTest("acceleration", "Three-axis acceleration", (
        TestField("acceleration_x", "X-axis acceleration", "m/s^2"),
        TestField("acceleration_y", "Y-axis acceleration", "m/s^2"),
        TestField("acceleration_z", "Z-axis acceleration", "m/s^2")), "imu"),
    FixedTest("angular_velocity", "Three-axis angular velocity", (
        TestField("angular_velocity_x", "X-axis angular velocity", "deg/s"),
        TestField("angular_velocity_y", "Y-axis angular velocity", "deg/s"),
        TestField("angular_velocity_z", "Z-axis angular velocity", "deg/s")), "imu"),
    FixedTest("ecg_heart_rate", "ECG-derived heart rate", (
        TestField("ecg_heart_rate", "ECG heart rate", "bpm"),), "ecg"),
    FixedTest("ecg_hrv_rmssd", "ECG-derived HRV (RMSSD)", (
        TestField("ecg_hrv_rmssd", "ECG HRV (RMSSD)", "ms"),), "ecg"),
    FixedTest("skin_conductance", "Skin conductance", (
        TestField("skin_conductance", "Skin conductance", "uS"),), "eda"),
    # NASA-STD-3001 Rev C source-separated dose quantities; not medical thresholds.
    # Values are supplied by suitable external dosimetry/models, never from counts.
    FixedTest("career_effective_dose", "Career effective dose (reported)", (
        TestField("career_effective_dose", "Career effective dose", "mSv"),),
        "radiation", manual_enabled=False),
    FixedTest("gcr_effective_dose_rate", "GCR effective dose rate (reported)", (
        TestField("gcr_effective_dose_rate", "GCR effective dose rate", "mSv/day"),),
        "radiation_environment", manual_enabled=False),
    FixedTest("spe_effective_dose", "Solar event effective dose (reported)", (
        TestField("spe_effective_dose", "Solar event effective dose", "mSv"),),
        "radiation", manual_enabled=False),
    FixedTest("nuclear_effective_dose", "Nuclear-source effective dose (reported)", (
        TestField("nuclear_effective_dose", "Nuclear-source effective dose", "mSv"),),
        "radiation", manual_enabled=False),
    FixedTest("lens_dose", "Eye lens dose (reported)", (
        TestField("lens_dose", "Eye lens dose", "mGy-Eq"),),
        "radiation", manual_enabled=False),
    FixedTest("skin_dose", "Skin dose (reported)", (
        TestField("skin_dose", "Skin dose", "mGy-Eq"),),
        "radiation", manual_enabled=False),
    FixedTest("bfo_dose", "Blood-forming organ dose (reported)", (
        TestField("bfo_dose", "Blood-forming organ dose", "mGy-Eq"),),
        "radiation", manual_enabled=False),
    FixedTest("co2_concentration", "Habitat CO2 concentration", (
        TestField("co2_concentration", "CO2", "ppm"),), "co2"),
    FixedTest("sound_level", "Habitat sound level", (
        TestField("sound_level", "Sound level", "dBA"),), "noise"),
    FixedTest("audio_relative_rms", "Relative microphone RMS", (
        TestField("audio_relative_rms", "Audio RMS", "relative"),), "noise"),
    FixedTest("bioimpedance", "Bioimpedance measurement", (
        TestField("bioimpedance", "Impedance", "ohm"),), "bioimpedance"),
    FixedTest("eye_image_captured", "Eye image capture", (
        TestField("eye_image_captured", "Image captured", "count"),),
        "eye_imaging", manual_enabled=False),
)

TESTS_BY_ID = {test.test_id: test for test in FIXED_TESTS}
FIELDS_BY_MEASUREMENT = {
    field.measurement_type: field
    for test in FIXED_TESTS
    for field in test.fields
}
MANUAL_TESTS = tuple(test for test in FIXED_TESTS if test.manual_enabled)

assert len(TESTS_BY_ID) == len(FIXED_TESTS), "Duplicate test identifiers"
assert len(FIELDS_BY_MEASUREMENT) == sum(len(t.fields) for t in FIXED_TESTS), (
    "Duplicate measurement identifiers"
)
