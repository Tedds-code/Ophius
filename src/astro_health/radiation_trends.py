# Made in cooperation with ChatGPT
"""Conservative radiation history, true window comparisons, and simple trends.

Never sums dose COUNTER snapshots. Does not convert GCR environment rates into
an astronaut's personal dose. Unverified dose semantics disable forecasting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from typing import Any

from astro_health.astronaut_assessment import RADIATION_NAMES

COUNTER_NAMES = ('career_effective_dose', 'lens_dose', 'skin_dose', 'bfo_dose')
UNITS = {'career_effective_dose': 'mSv', 'lens_dose': 'mGy-Eq',
         'skin_dose': 'mGy-Eq', 'bfo_dose': 'mGy-Eq'}
WINDOWS = {'30_days': 30, '1_year': 365}


@dataclass(frozen=True)
class DoseSample:
    timestamp: datetime
    value: float
    source: str
    reading_id: int | None


@dataclass
class DoseAnalysis:
    measurement_type: str
    unit: str
    latest: float | None = None
    sample_count: int = 0
    windows: dict[str, float] = field(default_factory=dict)
    career: float | None = None
    observed_delta: float | None = None
    observed_days: float | None = None
    daily_change_estimate: float | None = None
    forecast_days_to_limit: float | None = None
    forecast_limit: float | None = None
    notes: list[str] = field(default_factory=list)


def _aware(value) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _valid(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def collect_samples(readings, *, metadata_by_id=None) -> dict[str, list[DoseSample]]:
    """No database writes. Keep dose units separate and source-isolated."""
    result: dict[str, list[DoseSample]] = {key: [] for key in COUNTER_NAMES}
    for reading in readings:
        if reading is None or reading.quality in ('invalid', 'suspect'):
            continue
        timestamp = _aware(reading.timestamp)
        if timestamp is None:
            continue
        meta = (metadata_by_id(reading.id) or {}) if metadata_by_id and reading.id else {}
        source = str(meta.get('device_id') or reading.source or 'unknown')
        for m in reading.measurements:
            if m.measurement_type in result and m.unit == UNITS[m.measurement_type] and _valid(m.value):
                result[m.measurement_type].append(
                    DoseSample(timestamp, float(m.value), source, reading.id))
    for samples in result.values():
        samples.sort(key=lambda s: (s.timestamp, s.reading_id or 0))
    return result


def _limit(config: dict, field: str, window='career') -> float | None:
    # Only the configured project values; never invent NASA limits.
    from astro_health.astronaut_assessment import normalized_rule, rule_name
    limits = []
    for key, rule in config['signals'].items():
        if rule_name(key, rule) == field and rule.get('window') == window:
            limit = normalized_rule(key, rule).get('critical_above')
            if _valid(limit) and limit > 0:
                limits.append(float(limit))
    return min(limits) if limits else None


def analyze_history(readings, config: dict, settings: dict, *, metadata_by_id=None,
                    as_of: datetime | None = None) -> dict[str, DoseAnalysis]:
    """Compute exact-endpoint rolling counter differences when possible.

    For a dose window, a counter snapshot must exist at the boundary +/- 60s
    and an end snapshot at as_of +/- 24h. Otherwise no numeric window is
    asserted. Forecast is a labeled constant-rate extrapolation requiring at
    least 3 monotone counter snapshots over at least 3 days.
    """
    as_of = _aware(as_of or datetime.now(timezone.utc))
    if as_of is None:
        raise ValueError('as_of must be timezone-aware')
    samples_by_name = collect_samples(readings, metadata_by_id=metadata_by_id)
    output = {}
    mode_by_name = settings.get('dose_semantics', {})
    for name in COUNTER_NAMES:
        result = DoseAnalysis(name, UNITS[name])
        output[name] = result
        samples = [s for s in samples_by_name[name] if s.timestamp <= as_of]
        if not samples:
            result.notes.append('No saved NASA-aligned dose observations')
            continue
        # Never mix two dosimeters: use latest device and note other devices.
        source = samples[-1].source
        if len({s.source for s in samples}) > 1:
            result.notes.append('Multiple dose sources; trend restricted to latest source')
        samples = [s for s in samples if s.source == source]
        result.latest = samples[-1].value
        result.sample_count = len(samples)
        semantics = mode_by_name.get(name, {})
        if not isinstance(semantics, dict) or semantics.get('mode') != 'cumulative' or semantics.get('verified') is not True:
            result.notes.append('Dose counter semantics not confirmed; windows and forecasts unavailable')
            continue
        if any(b.timestamp == a.timestamp and b.value != a.value
               for a, b in zip(samples, samples[1:])):
            result.notes.append('Conflicting counters at the same timestamp; trend unavailable')
            continue
        if any(b.value < a.value for a, b in zip(samples, samples[1:])):
            result.notes.append('Cumulative counter decreased/reset; trend unavailable')
            continue
        if settings.get('career_history_complete'):
            result.career = samples[-1].value
        else:
            result.notes.append('Full career exposure baseline not confirmed')
        if len(samples) >= 2:
            elapsed = (samples[-1].timestamp - samples[0].timestamp).total_seconds() / 86400
            if elapsed > 0:
                result.observed_delta = samples[-1].value - samples[0].value
                result.observed_days = elapsed
        end = samples[-1]
        if (as_of - end.timestamp) <= timedelta(days=1):
            for window, days in WINDOWS.items():
                boundary = as_of - timedelta(days=days)
                boundary_samples = [s for s in samples if abs((s.timestamp - boundary).total_seconds()) <= 60]
                if boundary_samples:
                    start = min(boundary_samples, key=lambda s: abs((s.timestamp - boundary).total_seconds()))
                    result.windows[window] = end.value - start.value
        else:
            result.notes.append('Last dose observation is stale (>24h)')
        if not result.windows:
            result.notes.append('No exact rolling-window baseline; 30-day/year totals unavailable')
        if (as_of - end.timestamp) > timedelta(days=1):
            continue  # No future-day projection from stale history.
        if len({s.timestamp for s in samples}) < 3 or result.observed_days is None or result.observed_days < 3:
            result.notes.append('Forecast needs >=3 counter samples spanning >=3 days')
            continue
        # Estimate only with a known career baseline. Never treat a rate as dose.
        if result.career is None:
            continue
        delta = result.observed_delta
        if delta is None or delta <= 0:
            result.notes.append('No positive dose trend to extrapolate')
            continue
        rate = delta / result.observed_days
        result.daily_change_estimate = rate
        limit = _limit(config, name)
        if limit is not None:
            result.forecast_limit = limit
            result.forecast_days_to_limit = max(0.0, (limit - result.career) / rate)
            result.notes.append('Projection assumes constant historic rate; not a safety prediction')
    # Optionally incorporate verified interval increments.  They are separate
    # from the original SQLite counter snapshots: never add the two together.
    interval_file = settings.get('interval_history_file')
    if interval_file:
        from astro_health.radiation_intervals import load_intervals, summarize_intervals
        grouped = load_intervals(interval_file)
        for name, events in grouped.items():
            if name not in output:
                continue
            result = output[name]
            mode = settings.get('dose_semantics', {}).get(name, {})
            if mode.get('mode') != 'interval' or mode.get('verified') is not True:
                result.notes.append('Interval file present but dose mode not verified in settings')
                continue
            windows, lifetime, days = summarize_intervals(events, as_of)
            result.windows = windows
            result.sample_count = len(events)
            result.notes = ['Verified interval increments; unrecorded gaps invalidate window totals']
            if settings.get('career_history_complete') and lifetime is not None:
                result.career = lifetime
                result.latest = lifetime
            if lifetime is not None and days is not None and len(events) >= 3 and days >= 3:
                result.observed_delta = lifetime
                result.observed_days = days
                if result.career is not None and lifetime > 0:
                    result.daily_change_estimate = lifetime / days
                    limit = _limit(config, name)
                    if limit is not None:
                        result.forecast_limit = limit
                        result.forecast_days_to_limit = max(0.0,
                            (limit - result.career) / result.daily_change_estimate)
                        result.notes.append('Linear forecast only; assumes unchanging future exposure')
    return output
