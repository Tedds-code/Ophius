#!/usr/bin/env python3
"""Native desktop monitor; optional localhost JSON gateway, no browser dependency."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import queue
import signal
import sys
import threading

from astrohealth.monitor import Monitor
from astrohealth.server import make_server
from astrohealth.simulation import Simulator

ROOT = Path(__file__).resolve().parent


class AlertTracker:
    """Existing events stay visible, but are never replayed as new startup popups."""
    def __init__(self, monitor):
        self.seen = {(aid, str(event['id'])) for aid in monitor.profiles
                     for event in monitor.history(aid)['events']}

    def collect(self, monitor):
        new = []
        for member in monitor.list_profiles():
            aid = member['id']
            for alert in monitor.snapshot(aid)['alerts']:
                key = (aid, str(alert['id']))
                if key not in self.seen:
                    self.seen.add(key)
                    new.append({'aid': aid, 'alert': alert})
        return new


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--testing-mode', action='store_true', help='Enable synthetic value tests with a separate testing database')
    parser.add_argument('--port', type=int, help='Local gateway port: 8765 normally, 8766 in testing mode')
    parser.add_argument('--data-dir', type=Path, default=ROOT/'data')
    parser.add_argument('--headless', action='store_true', help='Run JSON gateway only, without a desktop window')
    parser.add_argument('--hidden', action='store_true', help='Start desktop monitoring hidden until a new warning')
    parser.add_argument('--desktop', action='store_true', help='Native desktop is the default')
    parser.add_argument('--open', action='store_true', help='Show native window (default); never opens a browser')
    parser.add_argument('--no-alert-browser', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args(argv)
    data_dir = args.data_dir.resolve()
    if args.testing_mode:data_dir = data_dir/'testing'
    port = args.port if args.port is not None else (8766 if args.testing_mode else 8765)
    data_dir.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(data_dir/'monitor.log', encoding='utf-8')]
    if sys.stderr is not None:handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s', handlers=handlers)
    desktop_enabled = not args.headless
    if desktop_enabled:
        import importlib.util
        if importlib.util.find_spec('PySide6') is None:
            raise RuntimeError('Run the included desktop setup once to install the embedded desktop runtime. No browser is launched.')
    monitor = None
    server = None
    stop = threading.Event()
    show_window = threading.Event()
    hide_window = threading.Event()
    notifications = queue.Queue(maxsize=100)
    worker_thread = None
    try:
        monitor = Monitor(data_dir, ROOT/'config', ROOT/'profiles')
        simulator = Simulator(monitor)
        tracker = AlertTracker(monitor)
        server = make_server(monitor, simulator, port, testing_mode=args.testing_mode, window_signals=show_window if desktop_enabled else None,
                             hide_signal=hide_window,stop_signal=stop)
        def halt(*_):stop.set()
        signal.signal(signal.SIGINT, halt);signal.signal(signal.SIGTERM, halt)
        def worker():
            while not stop.is_set():
                try:
                    if args.testing_mode:simulator.tick()
                    monitor.tick()
                    for event in tracker.collect(monitor):
                        if desktop_enabled:
                            try:notifications.put_nowait(event)
                            except queue.Full:
                                notifications.get_nowait();notifications.put_nowait(event)
                        logging.warning('%s: new %s warning',event['aid'],event['alert'].get('kind','condition'))
                except Exception:logging.exception('Monitoring iteration failed')
                stop.wait(.5)
        threading.Thread(target=server.serve_forever,name='json-gateway',daemon=True).start()
        worker_thread=threading.Thread(target=worker,name='monitor',daemon=True);worker_thread.start()
        if args.headless:
            if sys.stdout is not None:print(f'AstroHealth JSON gateway: http://127.0.0.1:{server.server_port}; simulation OFF',flush=True)
            while not stop.is_set():stop.wait(.5)
        else:
            from astrohealth.embedded_desktop import desktop_loop
            desktop_loop(f'http://127.0.0.1:{server.server_port}',notifications,stop,show_window,hide_window,
                         hidden=args.hidden and not args.open,testing_mode=args.testing_mode)
    finally:
        stop.set()
        if worker_thread is not None:worker_thread.join(timeout=5)
        if server is not None:server.shutdown();server.server_close()
        if monitor is not None:monitor.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
