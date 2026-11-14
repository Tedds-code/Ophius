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
    return ALIASES.get(key, key)


def normalized_rule(key: str, rule: dict) -> dict:
    result = dict(rule)
    result['measurement_type'] = rule_name(key, rule)
    if result['measurement_type'] == 'skin_temperature' and result.get('unit') in ('C', '°C'):
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
    applicable = [(key, normalized_rule(key, r)) for key, r in config['signals'].items()
                  if rule_name(key, r) == name]
    if not applicable:
        return Assessment(name, 'unassessed', value, unit, 'No configured personal measurement limit')

    found: list[tuple[str, str]] = []
    missing_context: list[str] = []
    for key, rule in applicable:
        if rule.get('unit') != unit:
            missing_context.append(f'{key}: expected {rule.get("unit")}, got {unit}')
            continue
        window = rule.get('window', 'instant')
        dose = value
        factor = 1.0
        if window in ('30_days', '1_year'):
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
        elif window not in ('instant', 'episode'):
            missing_context.append(f'{key}: unsupported comparison window {window}')
            continue
        if not _finite_number(dose):
            missing_context.append(f'{key}: invalid exposure')
            continue
        found.append((key, _check(dose, rule, factor)))

    for severity in ('critical', 'caution'):
        triggers = [key for key, level in found if level == severity]
        if triggers:
            return Assessment(name, severity, value, unit,
                              'Exceeds configured project reference: ' + ', '.join(triggers),
                              tuple(triggers))
    if missing_context:
        return Assessment(name, 'unassessed', value, unit,
                          '; '.join(missing_context), tuple(key for key, _ in found))
    if found:
        return Assessment(name, 'good', value, unit,
                          'Within applicable configured project reference(s)',
                          tuple(key for key, _ in found))
    return Assessment(name, 'unassessed', value, unit, 'No applicable comparison')


def load_settings(path: str | Path | None) -> dict:
    """Optional operator-entered provenance settings; safe defaults if absent."""
    if path is None or not Path(path).exists():
        return {'career_history_complete': False, 'mission_days': None,
                'dose_semantics': {}, 'interval_history_file': None}
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
    return {'career_history_complete': data.get('career_history_complete', False),
            'mission_days': days, 'dose_semantics': semantics,
            'interval_history_file': data.get('interval_history_file')}
