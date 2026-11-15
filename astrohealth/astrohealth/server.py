"""Local HTTP interface for the shared monitor service (standard library)."""
from __future__ import annotations

import json
import logging
import mimetypes
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .transport import MAX_BYTES, normalize_packet, strict_json
from .simulation import MODES
from . import __version__
from .report_simulation import simulate_report,measurement_connections,LAB_SCENARIOS,DOSE_SCENARIOS

ROOT = Path(__file__).resolve().parent.parent
LOG = logging.getLogger(__name__)


def make_server(monitor, simulator, port=8765, window_signals=None,hide_signal=None,stop_signal=None,testing_mode=False):
    startup_ids={aid:[e['id'] for e in monitor.history(aid)['events']] for aid in monitor.profiles}
    class Handler(BaseHTTPRequestHandler):
        server_version = 'AstroHealth/1.0'

        def log_message(self, fmt, *args):
            LOG.debug(fmt, *args)

        def send(self, code, payload, content_type='application/json; charset=utf-8'):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def body(self):
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Chunked requests are not supported')
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError as exc:
                raise ValueError('Invalid Content-Length') from exc
            if not 0 <= size <= MAX_BYTES:
                raise ValueError('Request exceeds size limit')
            if size and self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('Use Content-Type: application/json')
            value = strict_json(self.rfile.read(size)) if size else {}
            if not isinstance(value, dict):
                raise ValueError('JSON root must be an object')
            return value

        def route(self, method):
            try:
                # Protect the localhost service against cross-site writes and DNS rebinding.
                allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
                if self.headers.get('Host') not in allowed:
                    return self.send(403, {'error': 'Use the local dashboard address'})
                origin = self.headers.get('Origin')
                if origin and origin not in {f'http://{host}' for host in allowed}:
                    return self.send(403, {'error': 'Cross-origin requests are not allowed'})
                path = unquote(urlparse(self.path).path)
                if not path.startswith('/api/'):
                    if method != 'GET':
                        return self.send(405, {'error': 'Method not allowed'})
                    target=(ROOT/'static'/('index.html' if path=='/' else path.lstrip('/'))).resolve()
                    if (ROOT/'static').resolve() not in target.parents or not target.is_file():return self.send(404,{'error':'Not found'})
                    kind=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                    if kind.startswith('text/') or kind in {'application/javascript','application/json'}:kind+='; charset=utf-8'
                    return self.send(200,target.read_bytes(),kind)
                bits = path.removeprefix('/api/').strip('/').split('/')
                if bits == ['meta'] and method == 'GET':
                    return self.send(200, {**monitor.kb.meta(), 'native_desktop': window_signals is not None, 'app_version': __version__, 'buffer_seconds': 60,
                                           'testing_mode':testing_mode,'simulation_modes': list(MODES) if testing_mode else [],'threshold_catalog':monitor.kb.signals,
                                           'lab_scenarios':LAB_SCENARIOS if testing_mode else {},'dose_scenarios':DOSE_SCENARIOS if testing_mode else {}})
                if bits == ['monitor'] and method == 'GET':
                    return self.send(200, {'running': True, 'simulation': simulator.status(),
                                           'buffer_seconds': 60, 'daily_boundary': 'UTC','startup_event_ids':startup_ids})
                if bits == ['window', 'show'] and method == 'POST' and window_signals is not None:
                    self.body()
                    window_signals.set()
                    return self.send(200, {'shown': True})
                if bits==['window','hide'] and method=='POST' and hide_signal is not None:
                    self.body();hide_signal.set();return self.send(200,{'hidden':True})
                if bits==['window','quit'] and method=='POST' and stop_signal is not None:
                    self.body();stop_signal.set();return self.send(200,{'stopping':True})
                if bits == ['astronauts']:
                    if method == 'GET':
                        return self.send(200, monitor.list_profiles())
                    if method == 'POST':
                        return self.send(201, monitor.add_profile(self.body()))
                if len(bits) in (2, 3) and bits[0] == 'astronauts':
                    aid = bits[1]
                    sub = bits[2] if len(bits) == 3 else None
                    if method == 'GET' and sub is None:
                        return self.send(200, monitor.snapshot(aid))
                    if method == 'GET' and sub == 'history':
                        return self.send(200, monitor.history(aid))
                    if method == 'POST' and sub == 'lab':
                        payload=self.body()
                        if payload.get('synthetic') is True and not testing_mode:
                            return self.send(403,{'error':'Synthetic reports require testing mode; use the testing launcher'})
                        return self.send(200, monitor.import_lab(aid, payload))
                    if method == 'POST' and sub == 'ingest':
                        packet=normalize_packet(self.body(), monitor.kb)
                        synthetic=packet.get('source')=='simulation' or any((r.get('metadata',{}).get('synthetic_coverage') is True or r.get('metadata',{}).get('origin') in {'simulated','synthetic','simulation'}) for r in packet['readings'].values())
                        if synthetic and not testing_mode:
                            return self.send(403,{'error':'Synthetic packets require testing mode; use the testing launcher'})
                        return self.send(200, monitor.ingest(aid, packet))
                    if method == 'PUT' and sub == 'symptoms':
                        return self.send(200, monitor.update_symptoms(aid, self.body()))
                    if method == 'POST' and sub == 'simulate':
                        if not testing_mode:return self.send(403,{'error':'Simulations are available only in testing mode'})
                        return self.send(200, simulator.control(aid, self.body()))
                    if method=='POST' and sub=='simulate-report':
                        if not testing_mode:return self.send(403,{'error':'Simulations are available only in testing mode'})
                        return self.send(200,simulate_report(monitor,aid,self.body()))
                    if method=='POST' and sub=='connections':
                        return self.send(200,measurement_connections(monitor,aid,self.body().get('key')))
                    if method=='GET' and sub=='treatments':
                        profile=monitor.snapshot(aid)['profile']
                        entries=deepcopy(monitor.kb.treatment_catalog)
                        for entry in entries:entry['treatments']=[monitor.allergy_guard.treatment(profile,t) for t in entry['treatments']]
                        return self.send(200,entries)
                    if method == 'POST' and sub == 'forecast':
                        return self.send(200, monitor.forecast(aid, self.body()))
                    if method == 'POST' and sub == 'medication-check':
                        return self.send(200, monitor.check_medication(aid, self.body()))
                    if method == 'POST' and sub == 'medication':
                        return self.send(200, monitor.record_medication(aid, self.body()))
                    if method == 'PUT' and sub == 'allergies':
                        return self.send(200, monitor.update_allergies(aid, self.body()))
                    if method == 'POST' and sub == 'ack':
                        payload = self.body()
                        if not payload.get('event_id'):
                            raise ValueError('event_id is required')
                        return self.send(200, monitor.acknowledge(aid, payload['event_id']))
                self.send(404, {'error': 'Unknown endpoint'})
            except KeyError:
                self.send(404, {'error': 'Astronaut or event not found'})
            except (ValueError, TypeError, OverflowError) as exc:
                self.send(400, {'error': str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                LOG.exception('API operation failed')
                self.send(500, {'error': 'Operation failed; see the monitor console'})

        def do_GET(self): self.route('GET')
        def do_POST(self): self.route('POST')
        def do_PUT(self): self.route('PUT')

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server
