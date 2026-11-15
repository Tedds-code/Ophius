#!/usr/bin/env python3
"""Windows/Linux launcher; Python 3.10+; no mandatory pip dependencies."""
from __future__ import annotations

import argparse
import logging
import queue
import signal
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

from astrohealth.monitor import Monitor
from astrohealth.server import make_server
from astrohealth.simulation import Simulator

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local astronaut health monitor')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path, default=ROOT/'data')
    parser.add_argument('--open', action='store_true', help='Open dashboard immediately')
    parser.add_argument('--desktop', action='store_true', help='Native warning windows (requires Tk)')
    parser.add_argument('--no-alert-browser', action='store_true', help='Do not open a browser when a warning starts')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    monitor = Monitor(args.data_dir.resolve(), ROOT/'config', ROOT/'profiles')
    simulator = Simulator(monitor)
    try:
        server = make_server(monitor, simulator, args.port)
    except OSError as exc:
        monitor.close()
        parser.exit(1, f'Cannot start local server: {exc}. Try --port 8766\n')
    url = f'http://127.0.0.1:{server.server_port}'
    stop = threading.Event()
    notifications = queue.Queue(maxsize=100)
    seen = set()

    def halt(*_):
        stop.set()

    signal.signal(signal.SIGINT, halt)
    signal.signal(signal.SIGTERM, halt)

    def worker():
        last_open = 0
        while not stop.is_set():
            try:
                simulator.tick()
                monitor.tick()
                outstanding = set()
                for astronaut in monitor.list_profiles():
                    aid = astronaut['id']
                    snap = monitor.snapshot(aid)
                    for alert in snap.get('alerts', []):
                        key = (aid, str(alert.get('id', alert.get('event_id', ''))))
                        if not alert.get('acknowledged') and not alert.get('acknowledged_at'):
                            outstanding.add(key)
                        if key in seen or alert.get('acknowledged') or alert.get('acknowledged_at'):
                            continue
                        seen.add(key)
                        message = f"{aid} · {alert.get('severity', alert.get('level', 'WARNING'))}\n{alert.get('message', alert.get('title', alert.get('name', 'New threshold warning')))}"
                        if args.desktop:
                            try:
                                notifications.put_nowait(message)
                            except queue.Full:
                                notifications.get_nowait()
                                notifications.put_nowait(message)
                        logging.warning('%s: new warning; inspect dashboard', aid)
                        if not args.no_alert_browser and time.monotonic()-last_open > 10:
                            webbrowser.open(f'{url}/?astronaut={quote(aid, safe="")}')
                            last_open = time.monotonic()
                seen.intersection_update(outstanding)
            except Exception:
                logging.exception('Monitoring iteration failed')
            stop.wait(0.5)

    http_thread = threading.Thread(target=server.serve_forever, name='http', daemon=True)
    worker_thread = threading.Thread(target=worker, name='monitor', daemon=True)
    http_thread.start()
    worker_thread.start()
    print(f'AstroHealth is monitoring. Dashboard: {url}', flush=True)
    print('Simulation is OFF. Close browser freely; keep this process running. Ctrl+C saves and exits.', flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        if args.desktop:
            from astrohealth.desktop import desktop_loop
            if not desktop_loop(notifications, url, stop):
                print('Tk unavailable: browser warnings remain enabled. Linux: install python3-tk for native windows.', flush=True)
        while not stop.is_set():
            stop.wait(0.5)
    finally:
        stop.set()
        worker_thread.join(timeout=5)
        server.shutdown()
        server.server_close()
        monitor.close()
        print('Daily summaries saved. Monitor stopped.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
