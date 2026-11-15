"""Fresh-style JSON device adapters. No device-specific drivers are implied."""
from __future__ import annotations

import hashlib
import json
import math
import socket
import statistics
from datetime import date, datetime, timedelta, timezone

MAX_BYTES = 2_000_000


def strict_json(data):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"Duplicate JSON key: {key}")
            out[key] = value
        return out

    def invalid(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            invalid(value)
        return result

    if len(data.encode('utf-8') if isinstance(data, str) else data) > MAX_BYTES:
        raise ValueError('JSON exceeds the 2 MB limit')
    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite_float)


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return float(value)


def pulse_rate(samples, fs):
    """Fresh's simple peak detector, for clean synthetic waveforms only."""
    fs = number(fs, 'sample_rate_hz')
    if fs <= 0 or not isinstance(samples, list) or not 10 <= len(samples) <= 20000:
        raise ValueError('A waveform needs 10–20000 samples and a positive sample rate')
    samples = [number(x, 'sample') for x in samples]
    span = max(samples) - min(samples)
    if span <= 1e-9:
        raise ValueError('Flat waveform: no valid heart-rate estimate; not proof of arrest')
    cutoff = min(samples) + 0.6 * span
    separation = max(1, round(0.30 * fs))
    peaks = []
    for i in range(1, len(samples)-1):
        if samples[i] > samples[i-1] and samples[i] >= samples[i+1] and samples[i] >= cutoff:
            if peaks and i-peaks[-1] < separation:
                if samples[i] > samples[peaks[-1]]:
                    peaks[-1] = i
            else:
                peaks.append(i)
    if len(peaks) < 2:
        raise ValueError('Too few identifiable waveform peaks')
    return 60 / statistics.mean((b-a)/fs for a, b in zip(peaks, peaks[1:]))


def normalize_packet(document, kb, channel='jsonl'):
    if not isinstance(document, dict):
        raise ValueError('Packet must be a JSON object')
    if 'readings' in document:
        out = dict(document)
        out.setdefault('source', channel)
        return out
    required = {'sensor', 'timestamp', 'data'}
    if not required <= document.keys() or not isinstance(document['data'], dict):
        raise ValueError('Fresh packet requires sensor, timestamp and data')
    sensor, data = document['sensor'], document['data']
    result = {}

    def coverage(value, end=False):
        # Fresh uses inclusive calendar dates; normalized intervals use exclusive endpoints.
        if isinstance(value, str) and len(value) == 10:
            day = date.fromisoformat(value) + (timedelta(days=1) if end else timedelta())
            return datetime.combine(day, datetime.min.time(), timezone.utc).isoformat()
        return value

    def add(key, value, unit, metadata=None):
        result[key] = {'value': number(value, key), 'unit': unit}
        if metadata is not None:
            result[key]['metadata'] = metadata

    if sensor in ('ppg', 'ecg'):
        samples = 'ir_samples' if sensor == 'ppg' else 'ecg_samples'
        if samples in data:
            add('heart_rate', pulse_rate(data[samples], data.get('sample_rate_hz')), 'bpm')
        elif 'heart_rate_bpm' in data:
            add('heart_rate', data['heart_rate_bpm'], 'bpm')
        if 'spo2_percent' in data:
            calibration = document.get('calibration_id')
            if not isinstance(calibration, str) or not calibration.strip() or len(calibration) > 128:
                raise ValueError('Device SpO2 requires calibration_id')
            add('spo2', data['spo2_percent'], '%')
        if sensor == 'ecg' and 'qtc_ms' in data:
            add('qtc_interval', data['qtc_ms'], 'ms')
    elif sensor == 'blood_pressure':
        for key in ('blood_pressure_systolic', 'blood_pressure_diastolic'):
            add(key, data.get(key), 'mmHg')
        s, d = (result[k]['value'] for k in ('blood_pressure_systolic', 'blood_pressure_diastolic'))
        if s <= d and not (s == d == 0):
            raise ValueError('Systolic pressure must exceed diastolic (except valid zero/zero)')
    elif sensor == 'thermistor':
        if 'temperature_c' in data:
            value = data['temperature_c']
        elif 'adc_count' in data:
            adc = number(data['adc_count'], 'adc_count')
            if not adc.is_integer():
                raise ValueError('adc_count must be an integer')
            if not 0 < adc < 4095:
                raise ValueError('ADC must be strictly between 0 and 4095')
            # Fresh's circuit: supply -> NTC -> ADC -> fixed resistor -> ground.
            resistance = 10000 * (4095-adc) / adc
            value = 1/(1/298.15 + math.log(resistance/10000)/3950)-273.15
        else:
            raise ValueError('Thermistor needs temperature_c or adc_count')
        add('skin_temperature', value, 'C')
    elif sensor == 'co2':
        if 'co2_1h_mmhg' not in data or data.get('sample_period_minutes') != 60:
            raise ValueError('CO2 needs an instrument-reported 60-minute average in mmHg')
        add('cabin_co2', data['co2_1h_mmhg'], 'mmHg', {
            'kind': 'reported_window', 'window': '1_hour_average',
            'verified': data.get('verified') is True,
            'coverage_start': data.get('coverage_start'), 'coverage_end': data.get('coverage_end')})
    elif sensor == 'dose_report':
        context = {'kind': 'reported_window', 'window': data.get('coverage_window'),
                   'coverage_start': data.get('coverage_start'), 'coverage_end': data.get('coverage_end'),
                   'verified': data.get('verified') is True,
                   'career_complete': data.get('career_complete') in (True, 'yes'),
                   'mission_days': data.get('mission_days')}
        for key, value in data.items():
            if key in ('coverage_window', 'coverage_start', 'coverage_end', 'verified', 'career_complete', 'mission_days'):
                continue
            rule = kb.signals.get(key)
            if not rule or rule.get('category') != 'radiation':
                raise ValueError(f'Unknown dosimetry quantity: {key}')
            add(key, value, rule['unit'], context.copy())
    elif sensor == 'lab_analyzer':
        raise ValueError('Import laboratory JSON through the manual blood-test import, not continuous monitoring')
    else:
        raise ValueError(f'Unsupported sensor: {sensor}')
    if not result:
        raise ValueError('Packet contains no supported readings')
    origin = document.get('origin', 'device')
    if origin not in ('device', 'simulated', 'replay'):
        raise ValueError('origin must be device, simulated or replay')
    for item in result.values():
        metadata = item.setdefault('metadata', {})
        for field, value in list(metadata.items()):
            if value is None:
                del metadata[field]
            elif field in ('coverage_start', 'coverage_end'):
                metadata[field] = coverage(value, end=field == 'coverage_end')
        metadata.update({
            'device_id': document.get('device_id', 'unspecified'),
            'calibration_id': document.get('calibration_id'), 'sensor': sensor,
            'origin': origin, 'transport': channel})
    return {'packet_id': document.get('packet_id') or hashlib.sha256(
                json.dumps(document, sort_keys=True, allow_nan=False).encode()).hexdigest(),
            'timestamp': document['timestamp'], 'source': 'simulation' if origin in ('simulated', 'replay') else channel,
            'quality': document.get('quality', 'ok'), 'readings': result}


def file_packets(path):
    with open(path, encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield strict_json(line)
                except ValueError as exc:
                    raise ValueError(f'Line {line_number}: {exc}') from exc


def tcp_packets(host, port, timeout=30):
    """Read newline-delimited packets from an existing device gateway."""
    with socket.create_connection((host, port), timeout=timeout) as connection:
        with connection.makefile('rb') as stream:
            while True:
                line = stream.readline(MAX_BYTES+1)
                if not line:
                    return
                yield strict_json(line)


def serial_packets(port, baudrate=115200):
    try:
        import serial
    except ImportError as exc:
        raise ValueError('Optional serial transport needs: python -m pip install pyserial') from exc
    with serial.Serial(port, baudrate=baudrate, timeout=1) as stream:
        while True:
            line = stream.readline(MAX_BYTES+1)
            if line:
                yield strict_json(line)
