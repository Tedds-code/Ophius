# Made in cooperation with ChatGPT
"""Session completion indicators and CLI summaries, using existing SQLite API."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from astro_health.astronaut_assessment import assess_measurement, load_rules, load_settings
from astro_health.radiation_trends import analyze_history


@dataclass(frozen=True)
class TestResult:
    name: str
    test_id: str
    recorded: bool
    status: str
    display_value: str
    explanation: str


@dataclass(frozen=True)
class SessionView:
    session_id: int
    session_status: str
    started_at: str
    ended_at: str | None
    reading_count: int
    recorded_tests: int
    total_tests: int
    tests: tuple[TestResult, ...]
    warnings: tuple[str, ...]


def evaluate_session(store, session_id: int, config: dict, settings: dict) -> SessionView:
    """Read-only assessment. Never updates stored reading quality or results."""
    from astro_health.fixed_tests import FIXED_TESTS

    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f'Session {session_id} not found')
    summary = store.summary(session_id)
    # Calculate dose windows once across saved history. Missing provenance
    # returns no windows rather than interpreting single snapshots as doses.
    dose_history = (radiation_for_store(store, config, settings)
                    if any(name in summary for name in ('career_effective_dose', 'lens_dose',
                        'skin_dose', 'bfo_dose')) else {})
    output = []
    all_warnings = []
    for test in FIXED_TESTS:
        measurements = [summary.get(field.measurement_type) for field in test.fields]
        recorded = bool(measurements) and all(m is not None for m in measurements)
        if not recorded:
            output.append(TestResult(test.display_name, test.test_id, False,
                                     'missing', '—', 'Not completed in this session'))
            continue
        assessments = []
        texts = []
        for field, saved in zip(test.fields, measurements):
            assert saved is not None
            semantics = settings.get('dose_semantics', {}).get(field.measurement_type, {})
            history = dose_history.get(field.measurement_type)
            career_verified = (settings.get('career_history_complete', False)
                               and isinstance(semantics, dict)
                               and semantics.get('mode') in ('cumulative', 'interval')
                               and semantics.get('verified') is True
                               and history is not None and history.career is not None)
            windows = dict(history.windows) if history is not None else {}
            if career_verified:
                windows['career'] = history.career
            assessment = assess_measurement(
                field.measurement_type, saved.value, saved.unit, config,
                career_history_complete=career_verified,
                mission_days=settings.get('mission_days'),
                mission_cumulative_verified=(field.measurement_type == 'nuclear_effective_dose'
                    and isinstance(semantics, dict)
                    and semantics.get('mode') == 'mission_cumulative'
                    and semantics.get('verified') is True),
                window_values=windows)
            assessments.append(assessment)
            label = field.display_name if len(test.fields) > 1 else ''
            texts.append(f'{label + ": " if label else ""}{saved.value:g} {saved.unit}')
        statuses = [a.status for a in assessments]
        status = ('critical' if 'critical' in statuses else
                  'caution' if 'caution' in statuses else
                  'unassessed' if 'unassessed' in statuses else 'good')
        explanations = '; '.join(dict.fromkeys(a.explanation for a in assessments))
        if status in ('critical', 'caution'):
            all_warnings.append(f'{test.display_name}: {status.upper()} — {explanations}')
        output.append(TestResult(test.display_name, test.test_id, True,
                                 status, ', '.join(texts), explanations))
    return SessionView(session.id, session.status, session.started_at,
                       session.ended_at, session.reading_count,
                       sum(t.recorded for t in output), len(output),
                       tuple(output), tuple(all_warnings))


def load_project_configuration(rules_path='config/thresholds.json',
                               settings_path='config/monitoring_settings.json'):
    return load_rules(rules_path), load_settings(settings_path)


def radiation_for_store(store, config, settings):
    from astro_health.sensor_history import metadata_by_reading

    def lookup(rid):
        try:
            return metadata_by_reading(store.database, rid)
        except Exception:
            return None
    readings = store.database.list_readings()
    return analyze_history(readings, config, settings, metadata_by_id=lookup)


def describe_reading(reading, rules_path='config/thresholds.json',
                     settings_path='config/monitoring_settings.json') -> list[str]:
    """Compact immediate CLI comparison; no assumed dose reporting windows."""
    config, settings = load_project_configuration(rules_path, settings_path)
    lines = []
    for m in reading.measurements:
        assessment = assess_measurement(
            m.measurement_type, m.value, m.unit, config, quality=reading.quality,
            mission_days=settings.get('mission_days'),
            mission_cumulative_verified=(m.measurement_type == 'nuclear_effective_dose' and
                settings.get('dose_semantics', {}).get(m.measurement_type, {}).get('mode') == 'mission_cumulative' and
                settings.get('dose_semantics', {}).get(m.measurement_type, {}).get('verified') is True),
            career_history_complete=(settings.get('career_history_complete', False) and
                settings.get('dose_semantics', {}).get(m.measurement_type, {}).get('mode') == 'cumulative' and
                settings.get('dose_semantics', {}).get(m.measurement_type, {}).get('verified') is True))
        lines.append(f'{assessment.status.upper()}: {m.measurement_type} '
                     f'{m.value:g} {m.unit} — {assessment.explanation}')
    return lines


def print_session_report(store, session_id: int, *,
                         rules_path='config/thresholds.json',
                         settings_path='config/monitoring_settings.json',
                         output=print):
    config, settings = load_project_configuration(rules_path, settings_path)
    view = evaluate_session(store, session_id, config, settings)
    output(f'\n=== Astronaut test status | session {session_id} ({view.session_status}) ===')
    output(f'Recorded tests: {view.recorded_tests}/{view.total_tests} — Session completion is not medical clearance')
    for test in view.tests:
        output(f'  {test.status.upper():11} | {test.name}: {test.display_value}')
    for warning in view.warnings:
        output('PROJECT THRESHOLD WARNING: ' + warning)
    radiation = radiation_for_store(store, config, settings)
    output('Radiation history (personal, NASA-aligned quantities only):')
    for field, result in radiation.items():
        if result.latest is None and not result.windows:
            continue
        windows = ', '.join(f'{k}: {v:g} {result.unit}' for k, v in result.windows.items())
        latest = f'{result.latest:g} {result.unit}' if result.latest is not None else 'unavailable'
        output(f'  {field}: latest {latest}; {windows or "rolling totals unavailable"}')
        if result.forecast_days_to_limit is not None:
            output(f'    Linear trend only: ~{result.forecast_days_to_limit:.1f} days to '
                   f'project career reference {result.forecast_limit:g} {result.unit}')
    output('PROJECT REFERENCES / EDUCATIONAL ONLY; not medical clearance or NASA compliance.')
    return view
