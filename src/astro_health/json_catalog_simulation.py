# Made in cooperation with ChatGPT
"""JSON-first, synthetic-only complete catalog and dated exposure history.

No historical exposure is inferred from a spot sensor sample. Synthetic
histories are explicitly labeled and must never be treated as verified human
measurements or a claim of NASA compliance.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
import json
import hashlib
import math
from pathlib import Path

from astro_health.astronaut_assessment import load_rules
from astro_health.models import MeasurementValue, Reading

FORMAT = 'astro_health_json_catalog_simulation_v1'
PERIOD_DAYS = {'30_days': 30, '1_year': 365, 'career': 365}


def _base(name):
    if name.endswith(('_male', '_female')):
        return name.rsplit('_', 1)[0]
    for period in ('_30d', '_1y', '_career'):
        if name.endswith(period):
            return name[:-len(period)]
    return name


def _bounds(rule):
    return [x for x in (rule.get('caution_below'), rule.get('caution_above'),
                        rule.get('critical_below'), rule.get('critical_above')) if x is not None]


def _reference_value(rules):
    lo = max((r['caution_below'] for r in rules if r.get('caution_below') is not None), default=0)
    hi = min((r['caution_above'] for r in rules if r.get('caution_above') is not None), default=None)
    if hi is None:
        hi = min((r['critical_above'] for r in rules if r.get('critical_above') is not None), default=None)
    if hi is None:
        return float(max(1, lo + 1))
    if any(r.get('critical_below') is not None for r in rules):
        lo = max(lo, max(r.get('critical_below', lo) for r in rules))
    if hi <= lo:
        raise ValueError('Inconsistent JSON caution range')
    return round((lo + hi) / 2, 4)


def _rate_for(base, rules):
    """Select a modest synthetic per-day dose below every stated window limit."""
    rates = []
    for key, rule in rules:
        threshold = rule.get('critical_above') or rule.get('caution_above')
        if threshold is None:
            continue
        window = rule.get('window')
        if window in PERIOD_DAYS:
            rates.append(threshold / PERIOD_DAYS[window])
        elif window == 'per_mission_year':
            rates.append(threshold / 365.25)
    if not rates:
        raise ValueError(f'No dose threshold for {base}')
    return min(rates) * 0.2


def _severity(value, rule, scale=1):
    for status in ('critical', 'caution'):
        lower = rule.get(status + '_below')
        upper = rule.get(status + '_above')
        if lower is not None and value < lower * scale:
            return status
        if upper is not None and value > upper * scale:
            return status
    return 'good'


def simulate_catalog(config: dict, *, days: int = 365, profile: str = 'normal', end_date: date | None = None) -> dict:
    """Generate dated synthetic measurements and one result for EVERY JSON rule.

    Career means complete *fictional* career of the simulated astronaut, whose
    start and end dates are both within this generated history. Real imported
    history must never inherit this synthetic provenance.
    """
    if profile not in ('normal', 'mixed'):
        raise ValueError('profile must be normal or mixed')
    if isinstance(days, bool) or not isinstance(days, int) or days < 365 or days > 3660:
        raise ValueError('days must be 365..3660 (annual and career windows)')
    signals = config.get('signals')
    if not isinstance(signals, dict) or not signals:
        raise ValueError('JSON must contain signals')
    end_date = end_date or datetime.now(timezone.utc).date()
    start = end_date - timedelta(days=days - 1)
    grouped = {}
    dose_groups = {}
    for key, rule in signals.items():
        if rule.get('category') == 'radiation':
            dose_groups.setdefault(_base(key), []).append((key, rule))
        else:
            grouped.setdefault(_base(key), []).append((key, rule))
    units = {}
    values = {}
    for base, rows in grouped.items():
        rule_units = {rule['unit'] for _, rule in rows}
        if len(rule_units) != 1:
            raise ValueError(f'{base}: conflicting JSON units')
        units[base] = rule_units.pop()
        value = _reference_value([r for _, r in rows])
        if base == 'qtc_interval':
            value = 420.0  # Explicit synthetic demonstration, within both JSON limits.
        if base == 'vomiting_episodes':
            value = 0
        if profile == 'mixed' and base == 'hemoglobin':
            value = 12.5  # Male caution; female green, using one genuine value.
        values[base] = value
    dose_rates = {}
    for base, rows in dose_groups.items():
        unit_set = {r['unit'] for _, r in rows}
        if len(unit_set) != 1:
            raise ValueError(f'{base}: conflicting JSON dose units')
        units[base] = unit_set.pop()
        dose_rates[base] = _rate_for(base, rows)
    if profile == 'mixed' and 'blood_pressure_systolic' in signals:
        upper = signals['blood_pressure_systolic'].get('critical_above')
        if upper is not None:
            values['blood_pressure_systolic'] = upper + 1
    daily = []
    for n in range(days):
        day = start + timedelta(days=n)
        # Doses here are explicitly daily INCREMENTS, never cumulative snapshots.
        daily.append({'date': day.isoformat(),
                      'dose_increments': {key: round(rate, 12) for key, rate in dose_rates.items()},
                      'dose_units': {key: units[key] for key in dose_rates},
                      'measurements': {base: {'value': value, 'unit': units[base]}
                                       for base, value in values.items()},
                      'cabin_co2_one_hour_average_mmhg': values.get('cabin_co2'),
                      'synthetic': True})
    results = {}
    for key, rule in signals.items():
        base = _base(key)
        window = rule.get('window', 'instant')
        if rule.get('category') == 'radiation':
            if window == 'career':
                value = sum(record['dose_increments'][base] for record in daily)
                coverage = f'{days} daily synthetic increments; entire fictional career since {start.isoformat()}'
            elif window in PERIOD_DAYS:
                n = PERIOD_DAYS[window]
                value = sum(record['dose_increments'][base] for record in daily[-n:])
                coverage = f'{n} dated daily synthetic increments'
            elif window == 'per_mission_year':
                value = sum(record['dose_increments'][base] for record in daily)
                coverage = f'{days} dated synthetic mission days'
            else:
                raise ValueError(f'Unsupported dose window {window!r}: {key}')
            scale = days / 365.25 if window == 'per_mission_year' and rule.get('scales_with_mission_duration') else 1
        else:
            value = values[base]
            scale = 1
            coverage = ('synthetic hourly-average CO2 sample' if window == '1_hour_average'
                        else 'synthetic episode count' if window == 'episode'
                        else 'synthetic instant sensor/laboratory reading')
        results[key] = {'measurement_type': key, 'label': rule.get('label', key),
                        'value': round(value, 6), 'unit': rule['unit'], 'window': window,
                        'status': _severity(value, rule, scale), 'coverage': coverage,
                        'synthetic': True}
    conditions = {}
    for entry in config.get('condition_cutoffs', []):
        cid = entry['condition_id']
        op = entry.get('operator')
        v = entry.get('value')
        if entry.get('signal') == 'heart_rate':
            observed = values['heart_rate']
        elif entry.get('signal') == 'mission_day':
            observed = days
        elif entry.get('signal') == 'symptom_duration_hours':
            observed = 0
        else:
            raise ValueError(f'Unsupported condition signal: {cid}')
        triggered = ((observed >= v) if op == 'gte' else
                     (observed > v) if op == 'gt' else
                     (v[0] <= observed <= v[1]) if op == 'between' else None)
        if triggered is None:
            raise ValueError(f'Unsupported condition operator: {op}')
        conditions[cid] = {'signal': entry['signal'], 'value': observed,
                           'unit': entry['unit'], 'cutoff': v, 'operator': op,
                           'status': 'context_only' if op == 'between' else ('critical' if triggered else 'good'),
                           'synthetic': True}
    signature = hashlib.sha256(json.dumps(config['signals'], sort_keys=True).encode('utf-8')).hexdigest()
    return {'format': FORMAT, 'rules_sha256': signature, 'synthetic': True, 'profile': profile,
            'start_date': start.isoformat(), 'end_date': end_date.isoformat(),
            'career_history_complete': True, 'career_is_fictional': True,
            'units': units, 'latest_measurements': values, 'daily_history': daily,
            'assessments': results, 'condition_assessments': conditions,
            'reference_only': list(config.get('reference_only', {}).get('items', {})),
            'note': 'SYNTHETIC EDUCATIONAL DATA. Not actual instrument readings, clinical validation, or NASA compliance.'}


def save_simulation(path: str | Path, config: dict, *, days=365, profile='normal') -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    report = simulate_catalog(config, days=days, profile=profile)
    with dest.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2, allow_nan=False)
        f.write('\n')
    return dest


def reading_from_simulation(report: dict) -> Reading:
    if report.get('format') != FORMAT or report.get('synthetic') is not True:
        raise ValueError('Expected synthetic catalog report')
    # Store exactly one assessment-backed value per JSON rule in the session.
    measurements = tuple(MeasurementValue(key, val['value'], val['unit'])
                         for key, val in report['assessments'].items())
    timestamp = datetime.fromisoformat(report['end_date']).replace(tzinfo=timezone.utc)
    return Reading(source='simulated_json_catalog', measurements=measurements,
                   timestamp=timestamp)


def load_simulation(path: str | Path, config: dict) -> dict:
    """Recalculate results from dated increments; reject tampered summaries."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('format') != FORMAT or data.get('synthetic') is not True:
        raise ValueError('Unsupported or non-synthetic report')
    rows = data.get('daily_history', [])
    if len(rows) < 365:
        raise ValueError('At least one full year of dated history required')
    start = date.fromisoformat(rows[0]['date'])
    for index, row in enumerate(rows):
        if date.fromisoformat(row['date']) != start + timedelta(days=index):
            raise ValueError('Daily history has missing or duplicate dates')
        for base, v in row['dose_increments'].items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                raise ValueError('Invalid daily radiation increment')
    if set(data.get('assessments', {})) != set(config['signals']):
        raise ValueError('The report must cover exactly the active JSON rules')
    signature = hashlib.sha256(json.dumps(config['signals'], sort_keys=True).encode('utf-8')).hexdigest()
    if data.get('rules_sha256') != signature:
        raise ValueError('The history was generated for a different thresholds JSON')
    if data.get('career_is_fictional') is not True or data.get('career_history_complete') is not True:
        raise ValueError('Complete fictional career provenance is mandatory')
    if data.get('start_date') != rows[0]['date'] or data.get('end_date') != rows[-1]['date']:
        raise ValueError('History start/end dates inconsistent')
    for key, rule in config['signals'].items():
        saved = data['assessments'][key]
        if saved.get('unit') != rule['unit'] or saved.get('window') != rule.get('window', 'instant'):
            raise ValueError(f'Rule metadata mismatch: {key}')
        base = _base(key)
        window = rule.get('window', 'instant')
        if rule.get('category') == 'radiation':
            n = PERIOD_DAYS.get(window, len(rows))
            if window == 'per_mission_year':
                n = len(rows)
            vals = [r['dose_increments'][base] for r in rows[-n:]]
            actual = sum(vals)
            scale = len(rows) / 365.25 if window == 'per_mission_year' and rule.get('scales_with_mission_duration') else 1
        else:
            actual = rows[-1]['measurements'][base]['value']
            if rows[-1]['measurements'][base]['unit'] != rule['unit']:
                raise ValueError(f'Wrong daily value unit: {key}')
            scale = 1
        if abs(saved['value'] - actual) > 1e-5 or saved['status'] != _severity(actual, rule, scale):
            raise ValueError(f'Assessment does not match daily history for {key}')
    return data
