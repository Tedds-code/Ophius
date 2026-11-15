"""Local HTTP interface for the shared monitor service (standard library)."""
from __future__ import annotations

import json
import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .transport import MAX_BYTES, normalize_packet, strict_json

ROOT = Path(__file__).resolve().parent.parent
LOG = logging.getLogger(__name__)


def make_server(monitor, simulator, port=8765):
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
                    target = (ROOT/'static'/('index.html' if path == '/' else path.lstrip('/'))).resolve()
                    if (ROOT/'static').resolve() not in target.parents or not target.is_file():
                        return self.send(404, {'error': 'Not found'})
                    kind = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                    if kind.startswith('text/') or kind in ('application/javascript', 'application/json'):
                        kind += '; charset=utf-8'
                    return self.send(200, target.read_bytes(), kind)
                bits = path.removeprefix('/api/').strip('/').split('/')
                if bits == ['meta'] and method == 'GET':
                    return self.send(200, {**monitor.kb.meta(), 'buffer_seconds': 60,
                                           'simulation_modes': ['normal', 'caution', 'critical', 'cardiac_arrest', 'qtc']})
                if bits == ['monitor'] and method == 'GET':
                    return self.send(200, {'running': True, 'simulation': simulator.status(),
                                           'buffer_seconds': 60, 'daily_boundary': 'UTC'})
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
                        return self.send(200, monitor.import_lab(aid, self.body()))
                    if method == 'POST' and sub == 'ingest':
                        return self.send(200, monitor.ingest(aid, normalize_packet(self.body(), monitor.kb)))
                    if method == 'PUT' and sub == 'symptoms':
                        return self.send(200, monitor.update_symptoms(aid, self.body()))
                    if method == 'POST' and sub == 'simulate':
                        return self.send(200, simulator.control(aid, self.body()))
                    if method == 'POST' and sub == 'forecast':
                        return self.send(200, monitor.forecast(aid, self.body()))
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
