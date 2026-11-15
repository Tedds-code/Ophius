"""Explicit, continuously labelled synthetic device streams."""
from __future__ import annotations

import math
import threading
import time
import uuid
from datetime import timedelta

MODES = ('normal', 'caution', 'critical', 'cardiac_arrest', 'qtc', 'co2')


class Simulator:
    def __init__(self, monitor):
        self.monitor = monitor
        self.lock = threading.RLock()
        self.active = {}
        self.last_error = None

    def status(self):
        with self.lock:
            return {'active': {key: {k: v for k, v in value.items() if k != 'next'}
                               for key, value in self.active.items()}, 'last_error': self.last_error}

    def control(self, aid, payload):
        if not isinstance(payload, dict):
            raise ValueError('Simulation request must be an object')
        action = payload.get('action', 'once')
        mode = payload.get('mode', 'normal')
        if mode not in MODES:
            raise ValueError('Unknown simulation mode')
        self.monitor.snapshot(aid)
        with self.lock:
            if action == 'stop':
                self.active.pop(aid, None)
                self.monitor.set_stream_active(aid,'simulation',False)
            elif action == 'start' or (action == 'scenario' and mode == 'cardiac_arrest'):
                seconds = payload.get('interval_seconds', 2)
                if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 1 <= seconds <= 30:
                    raise ValueError('Simulation interval must be between 1 and 30 seconds')
                self.active[aid] = {'mode': mode, 'interval_seconds': seconds, 'step': 0,
                                    'next': time.monotonic()}
                self.monitor.set_stream_active(aid,'simulation',True)
            elif action in ('once', 'scenario'):
                if mode == 'cardiac_arrest':
                    self.active[aid] = {'mode': mode, 'interval_seconds': 2, 'step': 0, 'next': time.monotonic()}
                    self.monitor.set_stream_active(aid,'simulation',True)
                else:
                    self._send(aid, mode, 0)
                    self.monitor.set_stream_active(aid,'simulation',aid in self.active)
            else:
                raise ValueError('action must be start, stop, once or scenario')
        return self.monitor.snapshot(aid)

    def _send(self, aid, mode, step):
        # Fixtures, not physiology. No automatic blood tests or invented organ-dose sensor.
        profile = self.monitor.snapshot(aid)['profile']
        female = profile['personal_information']['gender'] == 'female'
        jitter = math.sin(step/5)
        values = {'heart_rate': (round(68+3*jitter, 1), 'bpm'),
                  'spo2': (98, '%'), 'blood_pressure_systolic': (114, 'mmHg'),
                  'blood_pressure_diastolic': (72, 'mmHg'), 'skin_temperature': (36.6, 'C'),
                  'qtc_interval': (430 if female else 410, 'ms')}
        if mode == 'caution':
            values['spo2'] = (94, '%')
        elif mode == 'critical':
            values['spo2'] = (89, '%')
        elif mode == 'qtc':
            values['qtc_interval'] = (515, 'ms')
        elif mode == 'cardiac_arrest':
            values['heart_rate'] = ((72, 155, 0)[min(step, 2)], 'bpm')
        now = self.monitor._now()
        readings = {key: {'value': value, 'unit': unit} for key, (value, unit) in values.items()}
        readings['cabin_co2'] = {'value': 3.2 if mode == 'co2' else round(2.0 + .05*jitter, 3), 'unit': 'mmHg',
            'metadata': {'kind': 'reported_window', 'window': '1_hour_average', 'verified': True,
                         'coverage_start': (now-timedelta(hours=1)).isoformat(), 'coverage_end': now.isoformat(),
                         'synthetic_coverage': True, 'sensor': 'co2',
                         'note': 'Synthetic instrument-reported one-hour average; not one hour of actual acquisition'}}
        packet = {'packet_id': uuid.uuid4().hex, 'timestamp': now.isoformat(),
                  'source': 'simulation', 'quality': 'ok',
                  'readings': readings}
        return self.monitor.ingest(aid, packet)

    def tick(self):
        with self.lock:
            for aid, job in list(self.active.items()):
                if time.monotonic() < job['next']:
                    continue
                try:
                    self._send(aid, job['mode'], job['step'])
                    job['step'] += 1
                    job['next'] = time.monotonic() + job['interval_seconds']
                    if job['mode'] == 'cardiac_arrest' and job['step'] >= 3:
                        self.active.pop(aid, None)
                        self.monitor.set_stream_active(aid,'simulation',False)
                except Exception as exc:
                    self.last_error = f'{aid}: {exc}'
                    self.active.pop(aid, None)
