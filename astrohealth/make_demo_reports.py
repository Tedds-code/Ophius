#!/usr/bin/env python3
"""Manually generate synthetic JSON examples for every supported lab/dose quantity."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parent


def documents(now=None):
    now = now or datetime.now(timezone.utc)
    catalog = json.loads((ROOT/'config'/'thresholds.json').read_text(encoding='utf-8'))['signals']
    labs, doses = {}, {}
    for key, rule in catalog.items():
        if rule['category'] == 'blood_panel':
            base = key.rsplit('_', 1)[0] if key.endswith(('_male', '_female')) else key
            labs.setdefault(base, []).append(rule)
        elif rule['category'] == 'radiation':
            doses.setdefault(rule['window'], {})[key] = rule
    values = {}
    for base, rules in labs.items():
        units = {rule['unit'] for rule in rules}
        if len(units) != 1:
            raise ValueError(f'Conflicting configured units for {base}')
        lows = [r['caution_below'] for r in rules if r.get('caution_below') is not None]
        highs = [r['caution_above'] for r in rules if r.get('caution_above') is not None]
        low, high = max(lows, default=0), min(highs, default=None)
        if high is not None and low >= high:
            raise ValueError(f'No shared normal demonstration band for {base}')
        value = (low+high)/2 if high is not None else low*1.2
        values[base] = {'value': round(value, 4), 'unit': next(iter(units))}
    output = {'blood_panel_all_supported.json': {
        'format': 'astro_health_blood_panel_v1', 'report_id': 'synthetic-'+uuid.uuid4().hex,
        'timestamp': now.isoformat(), 'synthetic': True,
        'note': 'Synthetic numerical fixture only; manually imported, not an actual laboratory test.',
        'measurements': values}}
    for window, rules in doses.items():
        days = {'30_days': 30, '1_year': 365, 'career': 730, 'per_mission_year': 1}[window]
        readings = {}
        for key, rule in rules.items():
            limit = rule.get('critical_above') or rule.get('caution_above')
            readings[key] = {'value': round(limit * .1, 5), 'unit': rule['unit'],
                'metadata': {'kind': 'reported_window', 'window': window, 'verified': True,
                    'coverage_start': (now-timedelta(days=days)).isoformat(), 'coverage_end': now.isoformat(),
                    'career_complete': window == 'career', 'synthetic_coverage': True,
                    'note': 'Declared synthetic report coverage; not actual acquired history'}}
        output['dose_'+window+'.json'] = {'packet_id': 'synthetic-'+uuid.uuid4().hex,
            'timestamp': now.isoformat(), 'source': 'simulation', 'quality': 'ok', 'readings': readings}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'examples'/'generated')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, document in documents().items():
        target = args.output/name
        target.write_text(json.dumps(document, indent=2)+'\n', encoding='utf-8')
        print(target)
    print('Import blood_panel_all_supported.json with Import blood test; dose files with Import sensor packet.')
    print('All files are simulation fixtures. Generate them before starting a new simulation to avoid older acquisitions.')


if __name__ == '__main__':
    main()
