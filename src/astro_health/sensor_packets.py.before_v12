# Made in cooperation with ChatGPT
# File: src/astro_health/sensor_packets.py
"""Common, hardware-independent JSON Lines packet format.

Each packet carries ONE device measurement or waveform window.  A physical
sensor needs a device-specific gateway that converts its native protocol into
this contract. No medical judgments or sensor calibration are implied.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


SENSOR_TYPES = (
    "thermistor", "ppg", "imu", "ecg", "eda", "radiation",
    "co2", "noise", "bioimpedance", "eye_imaging", "radiation_environment",
)
ORIGINS = ("simulated", "device", "replay")
MAX_PACKET_BYTES = 2_000_000
MAX_SAMPLES_PER_CHANNEL = 20_000


class PacketError(ValueError):
    """Invalid or unsupported sensor communication packet."""


def _valid_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, str):
        return 0 < len(value) <= 4096
    if isinstance(value, list):
        return (
            0 < len(value) <= MAX_SAMPLES_PER_CHANNEL
            and all(isinstance(v, (int, float))
                    and not isinstance(v, bool)
                    and math.isfinite(v) for v in value)
        )
    return False


@dataclass(frozen=True)
class SensorPacket:
    sensor: str
    timestamp: datetime
    data: dict[str, Any]
    origin: str = "device"
    device_id: str = "unspecified"
    calibration_id: str | None = None
    packet_id: str | None = None

    def __post_init__(self):
        if self.sensor not in SENSOR_TYPES:
            raise PacketError(f"Unsupported sensor: {self.sensor!r}")
        if self.origin not in ORIGINS:
            raise PacketError("origin must be simulated, device, or replay")
        if not isinstance(self.timestamp, datetime) or (
            self.timestamp.tzinfo is None
            or self.timestamp.utcoffset() is None
        ):
            raise PacketError("timestamp must include a UTC offset")
        if not isinstance(self.device_id, str) or not (1 <= len(self.device_id) <= 128):
            raise PacketError("device_id must be nonempty and at most 128 characters")
        if self.calibration_id is not None and (
            not isinstance(self.calibration_id, str)
            or not (1 <= len(self.calibration_id) <= 128)
        ):
            raise PacketError("calibration_id must be a nonempty string if supplied")
        if self.packet_id is not None and (
            not isinstance(self.packet_id, str)
            or not (1 <= len(self.packet_id) <= 128)
        ):
            raise PacketError("packet_id must be a nonempty identifier <= 128 characters")
        if not isinstance(self.data, dict) or not self.data:
            raise PacketError("data must be a nonempty object")
        if len(self.data) > 32:
            raise PacketError("Too many data channels")
        for key, value in self.data.items():
            if not isinstance(key, str) or not (1 <= len(key) <= 64):
                raise PacketError("Invalid channel name")
            if not _valid_value(value):
                raise PacketError(f"Invalid or nonfinite channel: {key}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensor": self.sensor,
            "timestamp": self.timestamp.astimezone(timezone.utc).isoformat(),
            "origin": self.origin,
            "device_id": self.device_id,
            "calibration_id": self.calibration_id,
            "packet_id": self.packet_id,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, obj: Mapping[str, Any]) -> "SensorPacket":
        if not isinstance(obj, dict):
            raise PacketError("Packet must be a JSON object")
        required = {"sensor", "timestamp", "data"}
        if not required.issubset(obj):
            raise PacketError(f"Missing fields: {sorted(required - obj.keys())}")
        if set(obj) - (required | {"origin", "device_id", "calibration_id", "packet_id"}):
            raise PacketError("Unexpected packet fields")
        timestamp = obj["timestamp"]
        if not isinstance(timestamp, str):
            raise PacketError("timestamp must be ISO 8601 text")
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PacketError("Invalid timestamp") from exc
        return cls(
            sensor=obj["sensor"], timestamp=timestamp,
            data=obj["data"], origin=obj.get("origin", "device"),
            device_id=obj.get("device_id", "unspecified"),
            calibration_id=obj.get("calibration_id"),
            packet_id=obj.get("packet_id"),
        )

    @classmethod
    def from_json(cls, line: str | bytes) -> "SensorPacket":
        if isinstance(line, bytes):
            if len(line) > MAX_PACKET_BYTES:
                raise PacketError("Packet line is too large")
            try:
                line = line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PacketError("Packet is not UTF-8") from exc
        if not isinstance(line, str) or len(line.encode("utf-8")) > MAX_PACKET_BYTES:
            raise PacketError("Packet line is too large")
        try:
            obj = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise PacketError("Packet contains invalid JSON") from exc
        return cls.from_dict(obj)
