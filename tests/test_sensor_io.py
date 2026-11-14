# Made in cooperation with ChatGPT
# File: tests/test_sensor_io.py

import json
import tempfile
import unittest
from pathlib import Path

from astro_health.database import Database
from astro_health.health_service import HealthService
from astro_health.sensor_io import SensorRecorder, packets_from_file, parse_jsonl_lines
from astro_health.sensor_packets import PacketError
from astro_health.sensor_simulators import simulated_stream


class TestSensorIO(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        database = Database(self.folder / "sensor_test.db")
        database.initialize()
        self.service = HealthService(database)

    def test_raw_log_links_to_sqlite_and_retains_source(self):
        path = self.folder / "logs" / "raw.jsonl"
        recorder = SensorRecorder(self.service, path)
        packets = list(simulated_stream("co2", count=3))
        results = [recorder.record(p) for p in packets]
        readings = self.service.list_readings()
        self.assertEqual(len(readings), 3)
        self.assertEqual({r.id for r in readings}, {item[0] for item in results})
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["reading_id"], results[0][0])
        self.assertEqual(rows[0]["packet"]["origin"], "simulated")
        self.assertEqual(readings[0].quality, "unassessed")

    def test_file_replay_from_usb_style_path(self):
        path = self.folder / "usb_drive_packets.jsonl"
        original = list(simulated_stream("eda", count=2))
        path.write_text("\n".join(p.to_json() for p in original) + "\n")
        restored = list(packets_from_file(path))
        self.assertEqual(restored, original)

    def test_bad_jsonl_reports_line_number(self):
        lines = ["\n", "{}\n"]
        with self.assertRaisesRegex(PacketError, "line 2"):
            list(parse_jsonl_lines(lines))

    def test_mixed_sensor_stream_is_stored(self):
        recorder = SensorRecorder(self.service, self.folder / "raw.jsonl")
        for sensor in ("co2", "eda", "imu", "radiation"):
            p = next(simulated_stream(sensor, count=1))
            recorder.record(p)
        self.assertEqual(len(self.service.list_readings()), 4)


# Additional optional-transport integration tests. These require no hardware.
import socket
import sys
import threading
import time
import types
from unittest.mock import patch
from astro_health.sensor_io import packets_from_serial, packets_from_tcp, send_packets_tcp
from astro_health.sensor_simulators import make_simulated_packet


class TestDeviceTransports(unittest.TestCase):
    def test_serial_adapter_reads_jsonl_from_mock_usb_port(self):
        packet = make_simulated_packet("co2")
        class FakeSerial:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def readline(self, size):
                return (packet.to_json() + "\n").encode("utf-8")
        fake_module = types.SimpleNamespace(Serial=FakeSerial)
        with patch.dict(sys.modules, {"serial": fake_module}):
            reader = packets_from_serial("COM99")
            got = next(reader)
            reader.close()
        self.assertEqual(got, packet)

    def test_offline_tcp_sender_and_receiver(self):
        # Bind a free local port for a short-lived loopback exchange.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        received = []
        failure = []
        def receive():
            try:
                received.extend(packets_from_tcp(
                    host="127.0.0.1", port=port, timeout_seconds=4,
                ))
            except Exception as exc:
                failure.append(exc)
        thread = threading.Thread(target=receive, daemon=True)
        thread.start()
        packet = make_simulated_packet("imu")
        for attempt in range(40):
            try:
                send_packets_tcp("127.0.0.1", port, [packet])
                break
            except ConnectionRefusedError:
                time.sleep(0.025)
        else:
            self.fail("TCP listener did not start")
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "TCP listener did not finish")
        self.assertEqual(failure, [])
        self.assertEqual(received, [packet])


if __name__ == "__main__":
    unittest.main()
