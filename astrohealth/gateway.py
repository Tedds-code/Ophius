#!/usr/bin/env python3
"""Forward Fresh JSONL/TCP/optional serial packets to the local running app."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from astrohealth.transport import file_packets, serial_packets, tcp_packets


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--astronaut', required=True)
    p.add_argument('--port', type=int, default=8765, help='Local app port')
    p.add_argument('--interval', type=float, default=0, help='Seconds between replayed file packets')
    p.add_argument('--replay-now', action='store_true', help='Rebase old file packets to now, label as synthetic')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--file')
    group.add_argument('--tcp', metavar='HOST:PORT')
    group.add_argument('--serial', metavar='PORT')
    args = p.parse_args()
    if args.interval < 0:
        p.error('--interval must be nonnegative')
    try:
        if args.file:
            packets = file_packets(args.file)
        elif args.tcp:
            host, port = args.tcp.rsplit(':', 1)
            packets = tcp_packets(host, int(port))
        else:
            packets = serial_packets(args.serial)
        count = 0
        for packet in packets:
            if args.replay_now:
                packet['timestamp'] = datetime.now(timezone.utc).isoformat()
                packet['origin'] = 'simulated'
                packet['source'] = 'simulation'
                packet.pop('packet_id', None)
            request = Request(f'http://127.0.0.1:{args.port}/api/astronauts/{args.astronaut}/ingest',
                              json.dumps(packet, allow_nan=False).encode(), {'Content-Type': 'application/json'}, method='POST')
            with urlopen(request, timeout=30) as response:
                response.read()
            count += 1
            print(f'Accepted packet {count}', flush=True)
            if args.interval:
                time.sleep(args.interval)
    except HTTPError as exc:
        print(exc.read().decode(), file=sys.stderr)
        return 1
    except (ValueError, OSError, URLError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
