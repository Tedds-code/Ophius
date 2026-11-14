# Made in cooperation with ChatGPT
"""Offline research-only reference checks for v7 sensor JSONL packets.

Never interprets snapshots as per-window or incremental dose, and never
converts engineering readings into clinical diagnoses. Does not alter SQLite.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from astro_health.fixed_tests import FIELDS_BY_MEASUREMENT
from astro_health.sensor_packets import SensorPacket
from astro_health.sensor_processing import process_packet


def load_thresholds(path: str | Path) -> dict:
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if config.get('version') != 2 or not isinstance(config.get('signals'), dict):
        raise ValueError('Expected v2 thresholds.json with signals object')
    for key, rule in config['signals'].items():
        name = rule.get('measurement_type')
        catalog = FIELDS_BY_MEASUREMENT.get(name)
        if rule.get('enabled_for_comparison'):
            if catalog is None or rule.get('unit') != catalog.unit:
                raise ValueError(f'Active rule {key} has unknown measurement or wrong unit')
        for bound in ('caution_below', 'caution_above', 'critical_below', 'critical_above'):
            v = rule.get(bound)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)):
                raise ValueError(f'Invalid bound {key}.{bound}')
    return config


def compare_measurement(measurement, rule_id: str, rule: dict, *, dose_window: str | None = None,
                        full_career_history: bool = False, mission_days: float | None = None) -> dict:
    """Comparison is only applicable when timeframe and basis are explicit.

    A snapshot dose is NOT equivalent to a 30-day/annual/career dose unless
    source metadata establishes that the value represents that entire window.
    """
    result = {'rule': rule_id, 'measurement_type': measurement.measurement_type,
              'value': measurement.value, 'unit': measurement.unit,
              'reference_verified': bool(rule.get('source', {}).get('verified_by_team', False)),
              'scope': 'research_only'}
    if not rule.get('enabled_for_comparison'):
        return {**result, 'status': 'disabled', 'reason': rule.get('disabled_reason', 'Rule disabled')}
    if rule.get('measurement_type') != measurement.measurement_type or rule.get('unit') != measurement.unit:
        return {**result, 'status': 'not_applicable'}
    if rule.get('requires_full_career_history') and not full_career_history:
        return {**result, 'status': 'insufficient_context', 'reason': 'Full career dose coverage not established'}
    if rule.get('requires_explicit_dose_window') and dose_window != rule.get('window'):
        return {**result, 'status': 'insufficient_context', 'reason': 'Sensor packet does not declare an assessed dose window'}
    if rule.get('requires_mission_duration') and (mission_days is None or not math.isfinite(mission_days) or mission_days <= 0):
        return {**result, 'status': 'insufficient_context', 'reason': 'Mission duration must be supplied for scaled nuclear reference'}
    x = measurement.value
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return {**result, 'status': 'invalid_measurement'}
    multiplier = mission_days / 365.25 if rule.get('scales_with_mission_duration') else 1.0
    checks = []
    for severity in ('critical', 'caution'):
        lo, hi = rule.get(severity + '_below'), rule.get(severity + '_above')
        if (lo is not None and x < lo * multiplier) or (hi is not None and x > hi * multiplier):
            checks.append(severity)
    return {**result, 'status': checks[0] if checks else 'within_configured_reference',
            'interpretation': 'Research comparison only; not a medical alert or compliance judgment',
            'reference_scale': multiplier}


def evaluate_reading(reading, config: dict, *, dose_window: str | None = None,
                     full_career_history: bool = False, mission_days: float | None = None) -> list[dict]:
    results = []
    if reading.quality == 'invalid':
        return [{'status': 'invalid_reading', 'reason': 'Original reading marked invalid'}]
    for m in reading.measurements:
        rules = [(key, r) for key, r in config['signals'].items() if r.get('measurement_type') == m.measurement_type]
        for key, r in rules:
            results.append(compare_measurement(m, key, r, dose_window=dose_window,
                                               full_career_history=full_career_history, mission_days=mission_days))
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Research-only threshold comparison of sensor JSONL packets')
    parser.add_argument('packets', type=Path, help='Existing JSONL packets, one sensor object per line')
    parser.add_argument('--rules', type=Path, default=Path('config/thresholds.json'))
    parser.add_argument('--mission-days', type=float, help='Mission duration for nuclear reference scaling')
    parser.add_argument('--full-career-history', action='store_true', help='Assert career counter includes all prior exposure')
    parser.add_argument('--dose-window', choices=['30_days','1_year','career'],
                        help='Use ONLY when input dose values have this verified reporting window')
    args = parser.parse_args(argv)
    cfg = load_thresholds(args.rules)
    errors = 0
    with args.packets.open(encoding='utf-8') as source:
        for line_num, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                pkt = SensorPacket.from_json(line)
                reading = process_packet(pkt).reading
                results = evaluate_reading(reading, cfg, dose_window=args.dose_window,
                                           full_career_history=args.full_career_history,
                                           mission_days=args.mission_days)
                print(json.dumps({'line': line_num, 'sensor': pkt.sensor,
                                  'timestamp': pkt.timestamp.isoformat(), 'comparisons': results}, allow_nan=False))
            except (ValueError, TypeError, KeyError) as exc:
                errors += 1
                print(json.dumps({'line': line_num, 'error': str(exc)}))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
