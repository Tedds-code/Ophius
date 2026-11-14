# Made in cooperation with ChatGPT
# File: src/astro_health/radiation_requirements.py
"""NASA-STD-3001 Rev C-aligned reporting of externally established quantities.

Separate streams by monitor, device, provenance, source, and environment.
Never add cumulative counters or conflate absorbed, equivalent and effective
quantities. Latest unambiguous snapshots are observations, not assessed limits.
"""
from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite

from astro_health.radiation import NASA_MEASUREMENT_FIELDS

NASA_REFERENCE = {
    'career_effective_dose_mSv': 600.0,  # V1 4030; whole career
    'reference_spe_effective_dose_mSv': 250.0,  # V1 4031 design reference event
    'nuclear_effective_dose_mSv_per_mission_year': 20.0,  # V1 4032, prorated
    'gcr_free_space_mSv_day': 1.3,  # V1 4033, habitat design >60 days
    'gcr_planetary_surface_mSv_day': 0.9,
}


def summarize_nasa_radiation(database, *, session_id=None):
    """Return separate reported quantities; never infer an individual's exposure.

    These are *snapshots* only: there is no assumption that measurements from
    different times, devices, or exposure classes can be added. Results are
    not a regulatory compliance assessment. Historical readings stay intact.
    """
    if session_id is not None and (isinstance(session_id, bool) or
                               not isinstance(session_id, int) or session_id <= 0):
        raise ValueError('session_id must be a positive integer')
    c = database._connect()
    try:
        sql = '''SELECT h.*, r.timestamp_utc FROM sensor_packet_history h
                 JOIN readings r ON r.id = h.reading_id
                 WHERE h.sensor IN ('radiation','radiation_environment')'''
        params = ()
        if session_id is not None:
            sql += ''' AND EXISTS(SELECT 1 FROM session_readings sr
                          WHERE sr.reading_id=h.reading_id AND sr.session_id=?)'''
            params = (session_id,)
        metadata = [dict(row) for row in c.execute(sql, params)]
    finally:
        c.close()
    grouped = defaultdict(lambda: defaultdict(list))
    warnings = []
    for meta in metadata:
        if meta.get('measurement_basis') != 'nasa_effective_dose_model':
            continue
        reading = database.get_reading(meta['reading_id'])
        if reading is None or reading.quality in ('invalid', 'suspect'):
            continue
        key = (meta['sensor'], meta['device_id'], meta['origin'],
               meta.get('ingest_channel') or 'unspecified',
               meta.get('calibration_id') or 'unspecified',
               meta.get('radiation_source') or 'unknown',
               meta.get('environment') or 'unspecified')
        for payload_name, (name, unit) in NASA_MEASUREMENT_FIELDS.items():
            for m in reading.measurements:
                if m.measurement_type != name or m.unit != unit:
                    continue
                v = m.value
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) or v < 0:
                    warnings.append(f'reading {reading.id}: invalid {name}')
                    continue
                grouped[key][payload_name].append((reading.timestamp.astimezone(timezone.utc),
                                                    reading.id, float(v)))
    streams = {}
    for key, measurements in sorted(grouped.items()):
        label = ' | '.join(key)
        fields = {}
        for payload_name, values in sorted(measurements.items()):
            by_time = defaultdict(set)
            for when, rid, value in values:
                by_time[when].add(value)
            latest = max(by_time)
            unique = by_time[latest]
            if len(unique) > 1:
                warnings.append(f'{label}: conflicting {payload_name} values at most recent timestamp')
                value = None
            else:
                value = next(iter(unique))
            # A snapshot is never the sum of prior snapshots.
            fields[payload_name] = {'value': value, 'unit': NASA_MEASUREMENT_FIELDS[payload_name][1],
                                    'timestamp': latest.isoformat(), 'observations': len(values),
                                    'semantics': 'latest_reported_snapshot'}
        streams[label] = fields
    return {'session_id': session_id, 'streams': streams, 'warnings': warnings,
            'reference': NASA_REFERENCE,
            'notice': 'No biological-dose derivation or NASA compliance assessment; externally established quantities only.'}
