# Made in cooperation with ChatGPT
"""Research-only packet comparison using the uploaded project JSON verbatim.

Configuration is normalized *in memory* to match stored sensor names/units.
A single packet is never assumed to provide a complete radiation interval,
career history or mission-to-date nuclear total. SQLite is never modified.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from astro_health.astronaut_assessment import load_rules, normalized_rule
from astro_health.fixed_tests import FIELDS_BY_MEASUREMENT
from astro_health.sensor_packets import SensorPacket
from astro_health.sensor_processing import process_packet


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_thresholds(path: str | Path) -> dict:
    """Load source limits intact; add an in-memory catalog mapping per rule."""
    original = load_rules(path)
    mapped = dict(original)
    mapped['signals'] = {}
    for rule_id, rule in original['signals'].items():
        effective = normalized_rule(rule_id, rule)
        field = FIELDS_BY_MEASUREMENT.get(effective['measurement_type'])
        compatible = field is not None and effective.get('unit') == field.unit
        # v1 has no 'enabled_for_comparison': do not treat that as an opt-out.
        # CO2 spot sensor ppm cannot be compared to an hourly mmHg limit.
        effective['enabled_for_comparison'] = bool(compatible)
        if not compatible:
            effective['disabled_reason'] = ('Sensor unit/meaning differs from JSON; '
                                             'use dashboard assessment with explicit context')
        mapped['signals'][rule_id] = effective
    return mapped


def compare_measurement(measurement, rule_id: str, rule: dict, *,
                        dose_window: str | None = None,
                        full_career_history: bool = False,
                        mission_days: float | None = None,
                        mission_cumulative_verified: bool = False) -> dict:
    result = {'rule': rule_id, 'measurement_type': measurement.measurement_type,
              'value': measurement.value, 'unit': measurement.unit,
              'reference_verified': bool(rule.get('source', {}).get('verified_by_team', False)),
              'scope': 'research_only'}
    if rule.get('measurement_type') != measurement.measurement_type:
        return {**result, 'status': 'not_applicable'}
    if rule.get('unit') != measurement.unit:
        return {**result, 'status': 'insufficient_context',
                'reason': 'JSON unit does not match packet; no unverified conversion performed'}
    if not rule.get('enabled_for_comparison'):
        return {**result, 'status': 'insufficient_context',
                'reason': rule.get('disabled_reason', 'Insufficient comparison context')}
    if not _finite(measurement.value):
        return {**result, 'status': 'invalid_measurement'}
    window = rule.get('window', 'instant')
    if window in ('30_days', '1_year') and dose_window != window:
        return {**result, 'status': 'insufficient_context',
                'reason': f'Explicitly verified {window} reporting window required'}
    if window == 'career' and not full_career_history:
        return {**result, 'status': 'insufficient_context',
                'reason': 'Full career-history coverage must be verified'}
    if window == 'per_mission_year' and (not mission_cumulative_verified or
            not _finite(mission_days) or mission_days <= 0):
        return {**result, 'status': 'insufficient_context',
                'reason': 'Verified mission-cumulative dose and positive mission duration required'}
    if window == '1_hour_average':
        return {**result, 'status': 'insufficient_context',
                'reason': 'A spot sensor reading is not a verified one-hour average'}
    if window not in ('instant', 'episode', '30_days', '1_year', 'career', 'per_mission_year'):
        return {**result, 'status': 'insufficient_context',
                'reason': f'Unsupported comparison window {window}'}
    factor = mission_days / 365.25 if window == 'per_mission_year' else 1.0
    x = measurement.value
    for level in ('critical', 'caution'):
        lo, hi = rule.get(f'{level}_below'), rule.get(f'{level}_above')
        if (lo is not None and x < lo * factor) or (hi is not None and x > hi * factor):
            return {**result, 'status': level,
                    'reference_scale': factor, 'interpretation': 'Project reference only'}
    return {**result, 'status': 'within_configured_reference',
            'reference_scale': factor, 'interpretation': 'Project reference only'}


def evaluate_reading(reading, config: dict, *, dose_window: str | None = None,
                     full_career_history: bool = False, mission_days: float | None = None,
                     mission_cumulative_verified: bool = False) -> list[dict]:
    if reading.quality in ('invalid', 'suspect'):
        return [{'status': 'invalid_reading', 'reason': f'Reading quality is {reading.quality}'}]
    results = []
    for measurement in reading.measurements:
        for rule_id, rule in config['signals'].items():
            if rule.get('measurement_type') == measurement.measurement_type:
                results.append(compare_measurement(measurement, rule_id, rule,
                              dose_window=dose_window, full_career_history=full_career_history,
                              mission_days=mission_days,
                              mission_cumulative_verified=mission_cumulative_verified))
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Research-only comparison of sensor JSONL')
    parser.add_argument('packets', type=Path)
    parser.add_argument('--rules', type=Path, default=Path('config/thresholds.json'))
    parser.add_argument('--mission-days', type=float)
    parser.add_argument('--full-career-history', action='store_true',
                        help='Only when full prior career coverage is independently verified')
    parser.add_argument('--mission-cumulative-verified', action='store_true',
                        help='Only when nuclear reading represents mission-to-date total')
    parser.add_argument('--dose-window', choices=['30_days', '1_year', 'career'],
                        help='Only when the packet source confirms this complete reporting window')
    args = parser.parse_args(argv)
    config = load_thresholds(args.rules)
    errors = 0
    with args.packets.open(encoding='utf-8') as source:
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                packet = SensorPacket.from_json(line)
                reading = process_packet(packet).reading
                comparisons = evaluate_reading(reading, config, dose_window=args.dose_window,
                    full_career_history=args.full_career_history, mission_days=args.mission_days,
                    mission_cumulative_verified=args.mission_cumulative_verified)
                print(json.dumps({'line': number, 'sensor': packet.sensor,
                    'timestamp': packet.timestamp.isoformat(), 'comparisons': comparisons}, allow_nan=False))
            except (ValueError, TypeError, KeyError) as exc:
                errors += 1
                print(json.dumps({'line': number, 'error': str(exc)}))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
