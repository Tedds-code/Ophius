# Made in cooperation with ChatGPT
"""Project-reference threshold evaluations for the astronaut dashboard.

A saved/complete test is not evidence of medical accuracy. In particular,
missing data or a limit that cannot legitimately be compared is never green.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

# Original (v1) project names -> NASA-only v7 stored measurement names.
ALIASES = {
    'cabin_co2': 'co2_concentration',
    'cumulative_effective_dose': 'career_effective_dose',
    'daily_gcr_dose_rate': 'gcr_effective_dose_rate',
    'solar_event_dose': 'spe_effective_dose',
    'nuclear_source_dose': 'nuclear_effective_dose',
    'blood_pressure_systolic': 'blood_pressure_systolic',
    'blood_pressure_diastolic': 'blood_pressure_diastolic',
    # The uploaded JSON carries terrestrial body-temperature reference limits.
    # Only the dedicated manual body-temperature test uses those limits.
    'skin_temperature': 'skin_temperature',
}
RADIATION_NAMES = frozenset({
    'career_effective_dose', 'gcr_effective_dose_rate',
    'spe_effective_dose', 'nuclear_effective_dose',
    'lens_dose', 'skin_dose', 'bfo_dose',
})

STATUS_RANK = {'critical': 4, 'caution': 3, 'unassessed': 2, 'good': 1, 'missing': 0}


@dataclass(frozen=True)
class Assessment:
    measurement_type: str
    status: str
    value: float | None
    unit: str
    explanation: str
    rule_ids: tuple[str, ...] = ()


def _finite_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def load_rules(path: str | Path) -> dict:
    """Support both the user's v1 JSON and v8's normalized v2 JSON.

    The original numeric thresholds remain authoritative for this *project*;
    verified_by_team and enabled_for_comparison are not treated as a veto.
    Gated contexts are still respected. Does not claim clinical validation.
    """
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(config, dict) or not isinstance(config.get('signals'), dict):
        raise ValueError('Expected thresholds JSON with a signals object')
    if config.get('version') not in (1, 2):
        raise ValueError('Unsupported thresholds.json version')
    for key, rule in config['signals'].items():
        if not isinstance(rule, dict):
            raise ValueError(f'Invalid rule: {key}')
        for bound in ('caution_below', 'caution_above', 'critical_below', 'critical_above'):
            x = rule.get(bound)
            if x is not None and not _finite_number(x):
                raise ValueError(f'Invalid numeric threshold: {key}.{bound}')
    return config


def rule_name(key: str, rule: dict) -> str:
    if rule.get('measurement_type'):
        return rule['measurement_type']
    for base in ('lens_dose', 'skin_dose', 'bfo_dose'):
        if key == base or key.startswith(base + '_'):
            return base
    # Sex-specific JSON limits share one actual lab / ECG measurement.
    # Both rules remain distinct and are evaluated independently.
    if key.endswith(('_male', '_female')):
        return key.rsplit('_', 1)[0]
    return ALIASES.get(key, key)


def normalized_rule(key: str, rule: dict) -> dict:
    result = dict(rule)
    result['measurement_type'] = rule_name(key, rule)
    if result['measurement_type'] in ('skin_temperature', 'temperature') and result.get('unit') in ('C', '°C'):
        result['unit'] = 'degC'
    if result['measurement_type'] == 'co2_concentration' and result.get('unit') == '%':
        # Exact unit conversion: one percent equals 10,000 ppm.
        result['unit'] = 'ppm'
        for b in ('caution_below', 'caution_above', 'critical_below', 'critical_above'):
            if result.get(b) is not None:
                result[b] *= 10000
    return result


def _check(value: float, rule: dict, factor: float = 1.0) -> str:
    for level in ('critical', 'caution'):
        lo, hi = rule.get(level + '_below'), rule.get(level + '_above')
        if lo is not None and value < lo * factor:
            return level
        if hi is not None and value > hi * factor:
            return level
    return 'good'


def assess_measurement(
    name: str, value: float | None, unit: str, config: dict,
    *, quality: str = 'unassessed', mission_days: float | None = None,
    career_history_complete: bool = False,
    mission_cumulative_verified: bool = False,
    window_values: dict[str, float] | None = None,
    cabin_pressure_mmhg: float | None = None,
) -> Assessment:
    """Assess a stored value against applicable PROJECT limits only.

    A missing window/career baseline is never silently replaced by a snapshot.
    Reference-only environmental design limits are not personal risk limits.
    """
    if value is None:
        return Assessment(name, 'missing', None, unit, 'No successful saved measurement')
    if not _finite_number(value):
        return Assessment(name, 'unassessed', value, unit, 'Non-finite reading')
    if quality in ('invalid', 'suspect'):
        return Assessment(name, 'unassessed', value, unit, f'Reading quality: {quality}')
    if name == 'gcr_effective_dose_rate':
        return Assessment(name, 'unassessed', value, unit,
                          'Environmental GCR dose-rate is not a personal dose or alert limit')
    # ECG-derived HR uses the same heart-rate limits; the underlying reading
    # remains identified as ECG-derived rather than silently renamed.
    lookup_name = 'heart_rate' if name == 'ecg_heart_rate' else name
    lookup_name = {'systolic_pressure': 'blood_pressure_systolic',
                   'diastolic_pressure': 'blood_pressure_diastolic'}.get(lookup_name, lookup_name)
    # Legacy sex-specific stored results remain readable; new imports use one value.
    if lookup_name.endswith(('_male', '_female')):
        lookup_name = lookup_name.rsplit('_', 1)[0]
    applicable = [(key, normalized_rule(key, r)) for key, r in config['signals'].items()
                  if rule_name(key, r) == lookup_name
                  or (name == 'cabin_co2_1h_mmhg' and key == 'cabin_co2')]
    if not applicable:
        return Assessment(name, 'unassessed', value, unit, 'No configured personal measurement limit')

    if value < 0 and unit not in ('degC', 'C', '°C'):
        return Assessment(name, 'unassessed', value, unit, 'Negative value is invalid for this measurement')
    found: list[tuple[str, str]] = []
    missing_context: list[str] = []
    for key, rule in applicable:
        window = rule.get('window', 'instant')
        dose = value
        # ppCO2 uses a time-averaged partial pressure (mmHg); sensor reports ppm.
        # Neither a spot ppm reading nor an assumed atmospheric pressure is enough.
        if name == 'co2_concentration' and rule.get('unit') == 'mmHg' and unit == 'ppm':
            if window != '1_hour_average' or window_values is None or '1_hour_average' not in window_values:
                missing_context.append(f'{key}: verified one-hour CO2 average in ppm required')
                continue
            if not _finite_number(cabin_pressure_mmhg) or cabin_pressure_mmhg <= 0:
                missing_context.append(f'{key}: measured cabin total pressure (mmHg) required')
                continue
            dose = window_values['1_hour_average'] * cabin_pressure_mmhg / 1_000_000.0
        elif rule.get('unit') != unit and not (rule.get('unit') == 'degC' and unit in ('C', '°C')):
            missing_context.append(f'{key}: expected {rule.get("unit")}, got {unit}')
            continue
        factor = 1.0
        if window in ('30_days', '1_year'):
            # A specifically named manually reported window still requires
            # operator verification before we can use its recorded value.
            if window_values is None or window not in window_values:
                missing_context.append(f'{key}: verified {window} exposure unavailable')
                continue
            dose = window_values[window]
        elif window == 'career':
            if not career_history_complete:
                missing_context.append(f'{key}: full career baseline not confirmed')
                continue
            if window_values is not None and 'career' in window_values:
                dose = window_values['career']
            elif name != 'career_effective_dose':
                missing_context.append(f'{key}: career exposure coverage unavailable')
                continue
        elif window == 'per_mission_year':
            if not mission_cumulative_verified:
                missing_context.append(f'{key}: mission-to-date nuclear dose basis not verified')
                continue
            if not _finite_number(mission_days) or mission_days <= 0:
                missing_context.append(f'{key}: mission duration not configured')
                continue
            factor = mission_days / 365.25
        elif window == '1_hour_average':
            if name == 'cabin_co2_1h_mmhg':
                # The manual field is defined as the one-hour average itself.
                # Unlike a spot sensor reading, its reporting window is explicit.
                pass
            elif name != 'co2_concentration':
                if window_values is None or window not in window_values:
                    missing_context.append(f'{key}: verified one-hour average required')
                    continue
                dose = window_values[window]
        elif window not in ('instant', 'episode'):
            missing_context.append(f'{key}: unsupported comparison window {window}')
            continue
        if not _finite_number(dose):
            missing_context.append(f'{key}: invalid exposure')
            continue
        found.append((key, _check(dose, rule, factor)))

    condition_note = ''
    if lookup_name == 'heart_rate':
        for condition in config.get('condition_cutoffs', []):
            if (condition.get('condition_id') == 'ventricular_dysrhythmia_risk'
                    and condition.get('signal') == 'heart_rate'
                    and condition.get('operator') == 'gte'
                    and _finite_number(condition.get('value')) and value >= condition['value']):
                condition_note = (f"; project dysrhythmia-risk screening cutoff met "
                                  f"({value:g} >= {condition['value']:g} bpm); not a diagnosis")
                break
    for severity in ('critical', 'caution'):
        triggers = [key for key, level in found if level == severity]
        if triggers:
            return Assessment(name, severity, value, unit,
                              'Exceeds configured project reference: ' + ', '.join(triggers) + condition_note,
                              tuple(triggers))
    if missing_context:
        return Assessment(name, 'unassessed', value, unit,
                          '; '.join(missing_context), tuple(key for key, _ in found))
    if found:
        return Assessment(name, 'good', value, unit,
                          'Within applicable configured project reference(s)' + condition_note,
                          tuple(key for key, _ in found))
    return Assessment(name, 'unassessed', value, unit, 'No applicable comparison')



def assess_sex_references(name: str, value: float | None, unit: str, config: dict,
                          *, quality: str = 'unassessed') -> dict[str, Assessment]:
    """Independently compare one recorded value to the two uploaded references.

    This does not infer the astronaut's sex; it is a side-by-side project
    reference display. Never manufactures values for a missing blood test.
    """
    stem = name.rsplit('_', 1)[0] if name.endswith(('_male', '_female')) else name
    results = {}
    for sex in ('male', 'female'):
        key = f'{stem}_{sex}'
        rule = config.get('signals', {}).get(key)
        if not isinstance(rule, dict):
            continue
        scoped = {'signals': {key: rule}, 'condition_cutoffs': config.get('condition_cutoffs', [])}
        assessment = assess_measurement(stem, value, unit, scoped, quality=quality)
        results[sex] = assessment
    return results


def load_settings(path: str | Path | None) -> dict:
    """Optional operator-entered provenance settings; safe defaults if absent."""
    if path is None or not Path(path).exists():
        return {'career_history_complete': False, 'mission_days': None,
                'dose_semantics': {}, 'interval_history_file': None,
                'cabin_pressure_mmhg': None, 'co2_average_verified': False,
                'co2_average_1h_ppm': None}
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('monitoring_settings.json must be an object')
    days = data.get('mission_days')
    if days is not None and (not _finite_number(days) or days <= 0):
        raise ValueError('mission_days must be positive')
    if not isinstance(data.get('career_history_complete', False), bool):
        raise ValueError('career_history_complete must be boolean')
    interval_file = data.get('interval_history_file')
    if interval_file is not None and (not isinstance(interval_file, str) or not interval_file.strip()):
        raise ValueError('interval_history_file must be a nonempty path or null')
    semantics = data.get('dose_semantics', {})
    if not isinstance(semantics, dict):
        raise ValueError('dose_semantics must be an object')
    pressure = data.get('cabin_pressure_mmhg')
    if pressure is not None and (not _finite_number(pressure) or pressure <= 0):
        raise ValueError('cabin_pressure_mmhg must be a positive measured pressure')
    average = data.get('co2_average_1h_ppm')
    if average is not None and (not _finite_number(average) or average < 0):
        raise ValueError('co2_average_1h_ppm must be a nonnegative measured 1-hour average')
    if not isinstance(data.get('co2_average_verified', False), bool):
        raise ValueError('co2_average_verified must be boolean')
    return {'co2_average_1h_ppm': average, 'co2_average_verified': data.get('co2_average_verified', False),
            'cabin_pressure_mmhg': pressure, 'career_history_complete': data.get('career_history_complete', False),
            'mission_days': days, 'dose_semantics': semantics,
            'interval_history_file': data.get('interval_history_file')}


# Condition-specific fields keep the condition identity; generic symptom hours
# cannot be safely assigned to one of multiple distinct conditions.
CONDITION_FIELDS = {
    'space_motion_sickness_duration_hours': 'space_motion_sickness',
    'nasal_congestion_duration_hours': 'nasal_congestion',
    'urinary_incontinence_duration_hours': 'urinary_incontinence',
    'urinary_retention_duration_hours': 'urinary_retention',
}


def assess_condition(field: str, value: float | None, unit: str, config: dict) -> Assessment:
    """Evaluate a specifically identified symptom duration using source cutoffs."""
    if value is None:
        return Assessment(field, 'missing', None, unit, 'No recorded symptom duration')
    if not _finite_number(value) or value < 0:
        return Assessment(field, 'unassessed', value, unit, 'Invalid symptom duration')
    if field == 'back_pain_space_adaptation_mission_day' and unit == 'mission_day':
        for rule in config.get('condition_cutoffs', []):
            if rule.get('condition_id') == 'back_pain_space_adaptation' and rule.get('operator') == 'between':
                bounds = rule.get('value')
                if isinstance(bounds, list) and len(bounds) == 2 and all(_finite_number(x) for x in bounds):
                    inside = bounds[0] <= value <= bounds[1]
                    message = (f"Mission day {value:g} is {'inside' if inside else 'outside'} "
                               f"the described back-pain onset window, days {bounds[0]:g}–{bounds[1]:g}. "
                               'Timing alone is not a symptom or health status.')
                    return Assessment(field, 'unassessed', value, unit, message, ('back_pain_space_adaptation',))
    condition = CONDITION_FIELDS.get(field)
    if condition is None or unit != 'hours':
        return Assessment(field, 'unassessed', value, unit, 'Condition identity or unit not supported')
    for rule in config.get('condition_cutoffs', []):
        if rule.get('condition_id') != condition:
            continue
        if rule.get('signal') != 'symptom_duration_hours':
            continue
        if rule.get('operator') == 'gt' and _finite_number(rule.get('value')):
            if value > rule['value']:
                return Assessment(field, 'critical', value, unit,
                    f"Duration exceeds project's {condition} cutoff of {rule['value']} hours",
                    (condition,))
            return Assessment(field, 'good', value, unit,
                f"Duration does not exceed project's {condition} cutoff of {rule['value']} hours",
                (condition,))
    return Assessment(field, 'unassessed', value, unit, 'No applicable condition cutoff')
