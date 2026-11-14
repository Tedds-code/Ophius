# Made in cooperation with ChatGPT
"""Explicit *interval-dose* JSONL support for accurately windowed exposures.

A record is one reported increment over [start, end). This adapter does not
claim a sensor produced that increment or derive it from counts/rates.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

VALID_UNITS = {'career_effective_dose': 'mSv',
               'lens_dose': 'mGy-Eq', 'skin_dose': 'mGy-Eq', 'bfo_dose': 'mGy-Eq'}


def utc(s):
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except (ValueError, AttributeError) as exc:
        raise ValueError('Invalid timestamp in interval record') from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('Interval timestamps must be timezone-aware')
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class DoseInterval:
    name: str
    unit: str
    dose_increment: float
    start: datetime
    end: datetime
    source_id: str


def load_intervals(path: str | Path) -> dict[str, list[DoseInterval]]:
    """Reject overlapping intervals, mixed units, and unverified increments."""
    grouped = defaultdict(list)
    with Path(path).open(encoding='utf-8') as handle:
        for lineno, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    raise ValueError('Record must be an object')
                name = obj['measurement_type']
                unit = obj['unit']
                if name not in VALID_UNITS or unit != VALID_UNITS[name]:
                    raise ValueError('Unsupported measurement type or unit')
                if obj.get('verified') is not True:
                    raise ValueError('Interval basis must be explicitly verified')
                dose = obj['dose_increment']
                if isinstance(dose, bool) or not isinstance(dose, (int, float)) or not math.isfinite(dose) or dose < 0:
                    raise ValueError('Dose increment must be finite and nonnegative')
                start, end = utc(obj['start']), utc(obj['end'])
                if start >= end:
                    raise ValueError('Interval start must be before end')
                source = obj['source_id']
                if not isinstance(source, str) or not source.strip():
                    raise ValueError('source_id is required')
                grouped[name].append(DoseInterval(name, unit, float(dose), start, end, source))
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f'Invalid interval JSONL line {lineno}: {exc}') from exc
    for name, events in grouped.items():
        events.sort(key=lambda x: (x.source_id, x.start, x.end))
        for prev, curr in zip(events, events[1:]):
            if prev.source_id == curr.source_id and curr.start < prev.end:
                raise ValueError(f'Overlapping interval dose records for {name} / {curr.source_id}')
    return dict(grouped)


def summarize_intervals(events: list[DoseInterval], as_of: datetime):
    """Exact 30/365-day totals only with contiguous full-window coverage."""
    if not events:
        return {}, None, None
    source = max(events, key=lambda e: e.end).source_id
    events = sorted((e for e in events if e.source_id == source and e.end <= as_of),
                    key=lambda x: x.start)
    if not events:
        return {}, None, None
    last = events[-1].end
    if (as_of - last) > timedelta(days=1):
        return {}, None, None
    windows = {}
    for window, days in [('30_days', 30), ('1_year', 365)]:
        target = as_of - timedelta(days=days)
        # We do not apportion partial intervals by assumed constant rate.
        start_index = next((i for i, e in enumerate(events)
                            if abs((e.start - target).total_seconds()) <= 60), None)
        if start_index is None:
            continue
        chosen = events[start_index:]
        if abs((chosen[-1].end - as_of).total_seconds()) > 60:
            continue
        if any(abs((b.start - a.end).total_seconds()) > 60 for a, b in zip(chosen, chosen[1:])):
            continue
        windows[window] = sum(e.dose_increment for e in chosen)
    elapsed_days = (events[-1].end - events[0].start).total_seconds() / 86400
    complete_sequence = not any(abs((b.start - a.end).total_seconds()) > 60
                                for a, b in zip(events, events[1:]))
    return windows, sum(e.dose_increment for e in events) if complete_sequence else None, elapsed_days if complete_sequence else None
