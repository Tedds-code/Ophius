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
    FixedTest("skin_temperature", "Skin surface temperature (thermistor)", (
        TestField("skin_temperature", "Skin surface temperature", "degC"),), "thermistor", manual_enabled=False),
    FixedTest("heart_rate", "Heart rate", (
        TestField("heart_rate", "Heart rate", "bpm"),), "ppg"),
    FixedTest("hrv_rmssd", "Heart-rate variability (RMSSD)", (
        TestField("hrv_rmssd", "HRV (RMSSD)", "ms"),), "ppg"),
    FixedTest("spo2", "Blood oxygen saturation", (
        TestField("spo2", "SpO2", "%"),), "ppg"),
    FixedTest("blood_pressure", "Blood pressure (oscillometric cuff)", (
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


# V11: Manual body-temperature reading is distinct from the skin thermistor.
FIXED_TESTS = (
    FixedTest('temperature', 'Body temperature (manual; body thermometer)',
              (TestField('temperature', 'Body temperature', 'degC'),)),
) + FIXED_TESTS

# V11: The same blood result or QTc interval is compared with both male and female
# reference rules.  Do not make separate sex-specific saved measurements.
BLOOD_TEST_FIELDS: tuple[TestField, ...] = (
    TestField('hemoglobin', 'Hemoglobin (Hb)', 'g/dL'),
    TestField('hematocrit', 'Hematocrit (Hct)', '%'),
    TestField('rbc', 'Red blood cells (RBC)', '10^12/L'),
    TestField('wbc', 'White blood cells (WBC)', '10^9/L'),
    TestField('neutrophils', 'Neutrophils', '10^9/L'),
    TestField('lymphocytes', 'Lymphocytes', '10^9/L'),
    TestField('monocytes', 'Monocytes', '10^9/L'),
    TestField('eosinophils', 'Eosinophils', '10^9/L'),
    TestField('basophils', 'Basophils', '10^9/L'),
    TestField('platelets', 'Platelets (PLT)', '10^9/L'),
    TestField('reticulocytes', 'Reticulocytes', '%'),
    TestField('d_dimer', 'D-dimer', 'mg/dL'),
)

# Blood tests are imported as a single JSON document, never individually typed.
FIXED_TESTS += tuple(FixedTest(field.measurement_type, field.display_name, (field,),
    manual_enabled=False) for field in BLOOD_TEST_FIELDS)

FIXED_TESTS += (
    FixedTest('qtc_interval', 'Corrected QT Interval (QTc)', (TestField('qtc_interval', 'Corrected QT Interval (QTc)', 'ms'),)),
    FixedTest('vomiting_episodes', 'Vomiting episodes (space motion sickness severity)', (TestField('vomiting_episodes', 'Vomiting episodes (space motion sickness severity)', 'episodes'),)),
    FixedTest('cardiovascular_disease_risk_dose', 'Cumulative Dose to Heart (Pathogenesis Threshold)', (TestField('cardiovascular_disease_risk_dose', 'Cumulative Dose to Heart (Pathogenesis Threshold)', 'Gy-eq'),)),
    FixedTest('circulatory_dose_30d', 'Dose to circulatory system - 30 days', (TestField('circulatory_dose_30d', 'Dose to circulatory system - 30 days', 'mGy-Eq'),)),
    FixedTest('circulatory_dose_1y', 'Dose to circulatory system - 1 year', (TestField('circulatory_dose_1y', 'Dose to circulatory system - 1 year', 'mGy-Eq'),)),
    FixedTest('circulatory_dose_career', 'Dose to circulatory system - career', (TestField('circulatory_dose_career', 'Dose to circulatory system - career', 'mGy-Eq'),)),
    FixedTest('cns_dose_30d', 'Dose to central nervous system (hippocampus) - 30 days', (TestField('cns_dose_30d', 'Dose to central nervous system (hippocampus) - 30 days', 'mGy'),)),
    FixedTest('cns_dose_1y', 'Dose to central nervous system (hippocampus) - 1 year', (TestField('cns_dose_1y', 'Dose to central nervous system (hippocampus) - 1 year', 'mGy'),)),
    FixedTest('cns_dose_career', 'Dose to central nervous system (hippocampus) - career', (TestField('cns_dose_career', 'Dose to central nervous system (hippocampus) - career', 'mGy'),)),
    FixedTest('cns_hze_dose_1y', 'CNS heavy ion dose Z>=10 - 1 year', (TestField('cns_hze_dose_1y', 'CNS heavy ion dose Z>=10 - 1 year', 'mGy'),)),
    FixedTest('cns_hze_dose_career', 'CNS heavy ion dose Z>=10 - career', (TestField('cns_hze_dose_career', 'CNS heavy ion dose Z>=10 - career', 'mGy'),)),
    FixedTest('cabin_co2_1h_mmhg', 'Cabin CO2 partial pressure (verified 1-hour average)', (TestField('cabin_co2_1h_mmhg', 'Cabin CO2 partial pressure (verified 1-hour average)', 'mmHg'),)),
    FixedTest('back_pain_space_adaptation_mission_day', 'Back-pain adaptation timing (mission day)', (TestField('back_pain_space_adaptation_mission_day', 'Back-pain adaptation timing (mission day)', 'mission_day'),)),
    FixedTest('space_motion_sickness_duration_hours', 'Space motion sickness duration', (TestField('space_motion_sickness_duration_hours', 'Space motion sickness duration', 'hours'),)),
    FixedTest('nasal_congestion_duration_hours', 'Nasal congestion duration', (TestField('nasal_congestion_duration_hours', 'Nasal congestion duration', 'hours'),)),
    FixedTest('urinary_incontinence_duration_hours', 'Urinary incontinence duration', (TestField('urinary_incontinence_duration_hours', 'Urinary incontinence duration', 'hours'),)),
    FixedTest('urinary_retention_duration_hours', 'Urinary retention duration', (TestField('urinary_retention_duration_hours', 'Urinary retention duration', 'hours'),)),
)

# Machine-reported cuff pressure is labeled by the uploaded JSON keys.
# Historical manually entered BP fields remain readable for old sessions.
FIXED_TESTS += (
    FixedTest('json_blood_pressure_systolic', 'Systolic cuff pressure',
              (TestField('blood_pressure_systolic', 'Systolic pressure', 'mmHg'),),
              'blood_pressure', manual_enabled=False),
    FixedTest('json_blood_pressure_diastolic', 'Diastolic cuff pressure',
              (TestField('blood_pressure_diastolic', 'Diastolic pressure', 'mmHg'),),
              'blood_pressure', manual_enabled=False),
)

FIXED_TESTS += (FixedTest('json_cabin_co2', 'Cabin CO2 one-hour mean',
    (TestField('cabin_co2', 'CO2 partial pressure', 'mmHg'),),
    'co2', manual_enabled=False),)

# JSON-defined dosimetry reports have explicit per-window measurement names.
# Retain the old catalog only for old-session compatibility; the live dashboard
# enumerates thresholds.json keys, not FIXED_TESTS.
from pathlib import Path as _Path
import json as _json
_json_rules = _json.loads((_Path(__file__).resolve().parents[2] / 'config' / 'thresholds.json').read_text(encoding='utf-8'))['signals']
_existing_names = {field.measurement_type for test in FIXED_TESTS for field in test.fields}
for _key, _rule in _json_rules.items():
    if _rule.get('category') == 'radiation' and _key not in _existing_names:
        FIXED_TESTS += (FixedTest('json_dosimetry_' + _key, _rule.get('label', _key),
            (TestField(_key, _rule.get('label', _key), _rule['unit']),),
            'dose_report', manual_enabled=False),)

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
