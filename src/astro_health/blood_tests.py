# Made in cooperation with ChatGPT
"""Strict offline blood-panel JSON import and project-reference test simulation.

Values in the sample JSON are SYNTHETIC and never represent lab analysis.
All supported units come from the fixed test catalog and uploaded JSON rules.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random

from astro_health.astronaut_assessment import load_rules, rule_name
from astro_health.fixed_tests import BLOOD_TEST_FIELDS
from astro_health.models import MeasurementValue, Reading

FORMAT = 'astro_health_blood_panel_v1'
BY_NAME = {field.measurement_type: field for field in BLOOD_TEST_FIELDS}
MAX_BYTES = 256 * 1024


def _duplicate_check(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def parse_blood_test(document: dict) -> Reading:
    """Parse a blood-test report with typed values and explicit source units.

    Expected: {"format": FORMAT, "measurements": {"hemoglobin":
    {"value": 14.1, "unit": "g/dL"}}, "timestamp": optional ISO8601}.
    Partial panels are allowed. One value is stored per analyte and both
    sex-specific reference bands are assessed at dashboard display time.
    """
    if not isinstance(document, dict):
        raise ValueError('Blood-test JSON root must be an object')
    if document.get('format') != FORMAT:
        raise ValueError(f'Expected blood-test format {FORMAT!r}')
    if not isinstance(document.get('synthetic', False), bool):
        raise ValueError('synthetic must be a boolean')
    measurements = document.get('measurements')
    if not isinstance(measurements, dict) or not measurements:
        raise ValueError('measurements must be a nonempty object')
    if any(key not in BY_NAME for key in measurements):
        unknown = sorted(key for key in measurements if key not in BY_NAME)
        raise ValueError('Unknown blood-test measurement(s): ' + ', '.join(unknown))

    rows = []
    for name, raw in measurements.items():
        field = BY_NAME[name]
        if not isinstance(raw, dict) or set(raw) != {'value', 'unit'}:
            raise ValueError(f'{name} needs an object with value and unit')
        value = raw['value']
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'{name} value must be a finite nonnegative number')
        if raw['unit'] != field.unit:
            raise ValueError(f'{name} unit must be {field.unit!r}; got {raw["unit"]!r}. Do not guess conversions')
        rows.append(MeasurementValue(name, float(value), field.unit))

    timestamp = document.get('timestamp')
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    elif isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('timestamp must be valid ISO8601 with UTC offset') from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError('timestamp must include a timezone')
    else:
        raise ValueError('timestamp must be an ISO8601 string')

    source = 'simulated_blood_panel' if document.get('synthetic') is True else 'blood_test_json'
    return Reading(source=source, measurements=tuple(rows), timestamp=timestamp)


def load_blood_test(path: str | Path) -> Reading:
    path = Path(path).expanduser()
    if path.suffix.lower() != '.json':
        raise ValueError('Blood test must be a .json file')
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Blood-test JSON exceeds 256 KiB maximum')
    document = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_duplicate_check)
    return parse_blood_test(document)


def simulate_blood_test(config: dict, *, profile: str = 'normal', seed: int | None = None) -> dict:
    """Synthetic numeric fixture derived from the uploaded JSON's caution bands.

    'normal': inside both sex-specific limits for all analytes.
    'mixed': selected fields exceed one or both caution bands, demonstrating
    independent male and female dashboard colors. Never invent critical limits.
    """
    if profile not in ('normal', 'mixed'):
        raise ValueError('Simulation profile must be normal or mixed')
    rng = random.Random(seed)
    measurements = {}
    for field in BLOOD_TEST_FIELDS:
        matches = [rule for key, rule in config['signals'].items()
                   if rule_name(key, rule) == field.measurement_type]
        if not matches:
            raise ValueError(f'Missing uploaded JSON reference for {field.measurement_type}')
        if any(rule.get('unit') != field.unit for rule in matches):
            raise ValueError(f'Unit mismatch for {field.measurement_type}')
        lower = max((rule['caution_below'] for rule in matches
                     if rule.get('caution_below') is not None), default=0.0)
        upper = min((rule['caution_above'] for rule in matches
                     if rule.get('caution_above') is not None), default=None)
        if upper is None or lower >= upper:
            raise ValueError(f'No shared configured range for {field.measurement_type}')
        # D-dimer reference units are taken literally, not used to infer
        # clinical plausibility; generate a very low synthetic test value.
        if field.measurement_type == 'd_dimer':
            value = round(min(0.2, upper * 0.1), 3)
        else:
            value = round(lower + (upper - lower) * rng.uniform(0.42, 0.58), 3)
        measurements[field.measurement_type] = {'value': value, 'unit': field.unit}
    if profile == 'mixed':
        # One shared Hb reading is caution for male and good for female.
        measurements['hemoglobin']['value'] = 12.5
        # Additional out-of-range synthetic values to exercise caution display.
        measurements['wbc']['value'] = 10.6
        measurements['platelets']['value'] = 425
    return {
        'format': FORMAT,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'synthetic': True,
        'simulation_profile': profile,
        'note': 'SYNTHETIC DATA ONLY; automatically generated for UI/test demonstrations.',
        'measurements': measurements,
    }


def save_simulated_blood_test(path: str | Path, config: dict, *,
                              profile: str = 'normal', seed: int | None = None) -> Path:
    """Write a fresh JSON fixture without ever overwriting an existing file."""
    target = Path(path)
    if target.suffix.lower() != '.json':
        raise ValueError('Simulation output must be a .json file')
    report = simulate_blood_test(config, profile=profile, seed=seed)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return target
