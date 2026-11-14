# Made in cooperation with ChatGPT
# File: src/astro_health/sensor_demo_sender.py
"""Run on a second laptop: python -m astro_health.sensor_demo_sender HOST SENSOR"""

import argparse

from astro_health.sensor_packets import SENSOR_TYPES
from astro_health.sensor_io import send_packets_tcp
from astro_health.sensor_simulators import simulated_stream


def main():
    parser = argparse.ArgumentParser(
        description="Send synthetic sensor JSONL over a trusted offline LAN."
    )
    parser.add_argument("host", help="Receiver laptop LAN IP address")
    parser.add_argument("sensor", choices=SENSOR_TYPES)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()
    if args.sensor == "eye_imaging":
        parser.error("Image files cannot be sent by path between laptops; use file import.")
    send_packets_tcp(
        args.host, args.port,
        simulated_stream(args.sensor, count=args.count, realtime=True),
    )
    print(f"Sent {args.count} synthetic {args.sensor} packets.")


if __name__ == "__main__":
    main()
