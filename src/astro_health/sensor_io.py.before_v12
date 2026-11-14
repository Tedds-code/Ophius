# Made in cooperation with ChatGPT
# File: src/astro_health/sensor_io.py
"""Offline JSONL, serial and local-TCP ingestion for physical/simulated data."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Iterable, Iterator, TextIO

from astro_health.sensor_packets import MAX_PACKET_BYTES, PacketError, SensorPacket
from astro_health.sensor_processing import ProcessedPacket, process_packet
from astro_health.sensor_history import (
    ensure_sensor_history, existing_packet_id, packet_fingerprint,
    store_packet_metadata,
)


class DuplicatePacket(PacketError):
    """A previously recorded packet was replayed; no new data were saved."""

    def __init__(self, reading_id: int):
        self.reading_id = reading_id
        super().__init__(f"Already recorded as reading {reading_id}")


def parse_jsonl_lines(lines: Iterable[str]) -> Iterator[SensorPacket]:
    """Parse newline-delimited packets from disk, USB, socket or serial text."""
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            yield SensorPacket.from_json(line)
        except PacketError as exc:
            raise PacketError(f"line {line_number}: {exc}") from exc


def packets_from_file(path: str | Path) -> Iterator[SensorPacket]:
    """Read packets from a JSONL file, including on a USB flash drive."""
    with Path(path).open("r", encoding="utf-8") as handle:
        lines = iter(lambda: handle.readline(MAX_PACKET_BYTES + 1), "")
        yield from parse_jsonl_lines(lines)


def packets_from_serial(port: str, *, baudrate: int = 115200) -> Iterator[SensorPacket]:
    """Read JSONL from a USB-serial device (optional: pip install pyserial).

    The connected microcontroller must transmit the documented JSONL
    protocol; this cannot automatically decode a sensor's proprietary bytes.
    """
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError(
            "USB serial requires optional 'pyserial': "
            "python -m pip install pyserial"
        ) from exc
    if not isinstance(baudrate, int) or isinstance(baudrate, bool) or baudrate <= 0:
        raise ValueError("baudrate must be a positive integer")
    with serial.Serial(port=port, baudrate=baudrate, timeout=2) as link:
        while True:
            line = link.readline(MAX_PACKET_BYTES + 1)
            if not line:
                continue  # port stays connected; no data yet
            if len(line) > MAX_PACKET_BYTES:
                raise PacketError("Serial packet line is too large")
            yield SensorPacket.from_json(line)


def packets_from_tcp(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_seconds: float = 30.0,
) -> Iterator[SensorPacket]:
    """Listen for one JSONL sender, optionally a second laptop on an offline LAN.

    No authentication or encryption is provided. Use a trusted, isolated LAN,
    bind to 127.0.0.1 by default, and do not expose the port to the internet.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)
        server.settimeout(timeout_seconds)
        connection, _address = server.accept()
        with connection:
            connection.settimeout(timeout_seconds)
            with connection.makefile("r", encoding="utf-8") as file:
                # Bound each line BEFORE it is parsed, even for untrusted senders.
                lines = iter(lambda: file.readline(MAX_PACKET_BYTES + 1), "")
                yield from parse_jsonl_lines(lines)


def send_packets_tcp(host: str, port: int, packets: Iterable[SensorPacket]) -> None:
    """Transmit standardized packets from another laptop on a trusted LAN."""
    with socket.create_connection((host, port), timeout=10) as connection:
        for packet in packets:
            connection.sendall((packet.to_json() + "\n").encode("utf-8"))


class SensorRecorder:
    """Save processed readings in existing SQLite; raw packets in JSONL.

    JSONL contains reading_id + complete original packet + processing notes.
    SQLite and JSONL are separate files and NOT transactionally atomic.
    """

    def __init__(self, health_service, raw_log_path: str | Path, *, image_root=None,
                 session_store=None, session_id=None, ingest_channel='unspecified'):
        self.service = health_service
        self.raw_log_path = Path(raw_log_path)
        self.image_root = Path(image_root) if image_root is not None else None
        self.session_store = session_store
        self.session_id = session_id
        if ingest_channel not in ('unspecified', 'simulation', 'jsonl', 'tcp', 'serial'):
            raise ValueError('Unsupported ingestion channel')
        self.ingest_channel = ingest_channel
        ensure_sensor_history(self.service.database)

    def record(self, packet: SensorPacket) -> tuple[int, ProcessedPacket]:
        processed = process_packet(packet, image_root=self.image_root)
        fingerprint = packet_fingerprint(packet)
        original_id = existing_packet_id(self.service.database, fingerprint)
        if original_id is not None:
            raise DuplicatePacket(original_id)
        self.raw_log_path.parent.mkdir(parents=True, exist_ok=True)
        # Confirm the log can be opened before modifying the database.
        with self.raw_log_path.open("a", encoding="utf-8") as output:
            reading_id = self.service.record_reading(processed.reading)
            if self.session_store is not None and self.session_id is not None:
                self.session_store.attach_reading(self.session_id, reading_id)
            store_packet_metadata(
                self.service.database, reading_id, fingerprint, packet,
                ingest_channel=self.ingest_channel,
            )
            entry = {
                "reading_id": reading_id,
                "session_id": self.session_id,
                "ingest_channel": self.ingest_channel,
                "packet": packet.to_dict(),
                "notes": list(processed.notes),
            }
            output.write(json.dumps(entry, allow_nan=False) + "\n")
            output.flush()
        return reading_id, processed
