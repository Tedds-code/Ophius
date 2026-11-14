# Made in cooperation with ChatGPT
"""JSON-first assessment for regular sensor sessions (not Fill All).

Only rule names in thresholds.json appear. Missing measurements stay missing;
recorded quantities with insufficient dose provenance stay unassessed.
"""
from __future__ import annotations

from datetime import date
from astro_health.astronaut_assessment import assess_measurement
from astro_health.sensor_history import metadata_by_reading


def _base_name(key):
    return key.rsplit('_', 1)[0] if key.endswith(('_male', '_female')) else key


def _dose_coverage(rule, meta):
    """Require report coverage, without granting it from a single snapshot."""
    if not meta or meta.get('sensor') != 'dose_report':
        return False, 'Dose snapshot is not an exposure-window report'
    window = rule.get('window')
    if meta.get('coverage_window') != window:
        return False, f'Expected {window} dose coverage'
    if window == 'career' and meta.get('career_complete') != 'yes':
        return False, 'Complete career dosimetry was not declared'
    start, end = meta.get('coverage_start'), meta.get('coverage_end')
    if not start or not end:
        return False, 'Coverage start/end dates not supplied'
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except (TypeError, ValueError):
        return False, 'Invalid coverage dates'
    if days <= 0:
        return False, 'Coverage dates are reversed'
    if window == '30_days' and days != 30:
        return False, '30 distinct calendar days are required'
    if window == '1_year' and days < 365:
        return False, 'A full year of coverage is required'
    if window == 'per_mission_year':
        mission_days = meta.get('mission_days')
        if not isinstance(mission_days, (int, float)) or mission_days <= 0 or days < mission_days:
            return False, 'Reported mission duration and complete coverage required'
    return True, f'Device-reported {days}-day coverage; independent verification required'


def evaluate_json_session(store, session_id, config, settings, *, after_reading_id=0):
    from astro_health.session_assessment import SessionView, TestResult
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f'No session {session_id}')
    latest = {}
    for reading in store.readings_for_session(session_id):
        if reading is None or (reading.id is not None and reading.id <= after_reading_id) or reading.quality in ('invalid', 'suspect'):
            continue
        for measure in reading.measurements:
            latest[measure.measurement_type] = (measure, reading)

    def result(name, key, measure_key, *, condition=False):
        observed = latest.get(measure_key)
        if observed is None:
            return TestResult(name, key, False, 'missing', '—',
                              'No reading recorded in this session')
        measure, reading = observed
        unit = measure.unit
        rule = config['signals'].get(key) if not condition else None
        value = measure.value
        note = ''
        if rule:
            if rule.get('unit') not in (unit, 'C' if unit == 'degC' else unit):
                status = 'unassessed'
                note = f'Units do not match JSON: {unit} versus {rule["unit"]}'
            elif rule.get('category') == 'radiation':
                metadata = metadata_by_reading(store.database, reading.id)
                ok, note = _dose_coverage(rule, metadata)
                if not ok:
                    status = 'unassessed'
                else:
                    scale = (metadata['mission_days'] / 365.25 if rule.get('scales_with_mission_duration') else 1)
                    status = _severity(value, rule, scale)
            elif rule.get('window') == '1_hour_average':
                metadata = metadata_by_reading(store.database, reading.id)
                if metadata and metadata.get('sensor') == 'co2':
                    status = _severity(value, rule)
                    note = 'Device reported a 60-minute average; calibration is external'
                else:
                    status = 'unassessed'
                    note = 'One-hour averaged instrument report required'
            else:
                status = _severity(value, rule)
                note = 'Assessed against exact JSON rule, not a medical diagnosis'
        else:
            from astro_health.astronaut_assessment import assess_condition
            assessment = assess_condition(measure_key, value, unit, config)
            status, note = assessment.status, assessment.explanation
        synthetic = reading.source.startswith(('simulated', 'replay'))
        label = f'{value:g} {unit}' + (' [SYNTHETIC]' if synthetic else '')
        return TestResult(name, key, True, status, label, note)

    output = []
    for key, rule in config['signals'].items():
        base = _base_name(key)
        output.append(result(rule.get('label', key), key, base))

    # Conditions are driven by specifically identified symptom reporting or
    # by heart rate. No symptom is silently manufactured by a sensor.
    condition_fields = {
        'space_motion_sickness': 'space_motion_sickness_duration_hours',
        'nasal_congestion': 'nasal_congestion_duration_hours',
        'urinary_incontinence': 'urinary_incontinence_duration_hours',
        'urinary_retention': 'urinary_retention_duration_hours',
        'back_pain_space_adaptation': 'back_pain_space_adaptation_mission_day',
    }
    for item in config.get('condition_cutoffs', []):
        cid = item['condition_id']
        if item.get('signal') == 'heart_rate':
            observed = latest.get('heart_rate')
            if observed is None:
                output.append(TestResult(cid, cid, False, 'missing', '—', 'No heart-rate reading'))
            else:
                value = observed[0].value
                active = value >= item['value'] if item['operator'] == 'gte' else value > item['value']
                output.append(TestResult(cid, cid, True, 'critical' if active else 'good',
                                         f'{value:g} bpm', 'JSON condition cutoff; not a diagnosis'))
        else:
            output.append(result(cid, cid, condition_fields[cid], condition=True))
    rows = tuple(output)
    warnings = tuple(f'{r.name}: {r.status.upper()}' for r in rows if r.status in ('critical', 'caution'))
    return SessionView(session.id, session.status, session.started_at, session.ended_at,
                       session.reading_count, sum(r.recorded for r in rows), len(rows),
                       rows, warnings)


def _severity(value, rule, scale=1):
    for severity in ('critical', 'caution'):
        lo, hi = rule.get(severity + '_below'), rule.get(severity + '_above')
        if lo is not None and value < lo * scale:
            return severity
        if hi is not None and value > hi * scale:
            return severity
    return 'good'
