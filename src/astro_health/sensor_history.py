# Made in cooperation with ChatGPT
# File: src/astro_health/sensor_history.py
"""Versioned packet identity and provenance metadata in SQLite.

Original sensor packets remain in JSONL. This table links a processed reading
back to its device and NASA-aligned radiation source metadata.
"""

from datetime import datetime, timezone
import hashlib
import json

from astro_health.radiation import radiation_specification


def ensure_sensor_history(database):
    """Add schema v3 without changing or removing existing readings/sessions."""
    database.initialize()
    connection = database._connect()
    try:
        with connection:
            connection.execute('''
                CREATE TABLE IF NOT EXISTS sensor_packet_history (
                    reading_id INTEGER PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    sensor TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    calibration_id TEXT,
                    packet_id TEXT,
                    particle_type TEXT,
                    count_mode TEXT,
                    dose_mode TEXT,
                    interval_seconds REAL,
                    FOREIGN KEY (reading_id) REFERENCES readings(id)
                        ON DELETE RESTRICT
                )
            ''')
            connection.execute('''
                INSERT OR IGNORE INTO schema_migrations
                    (version, applied_at, description)
                VALUES (3, ?, 'Sensor packet provenance and identity')
            ''', (datetime.now(timezone.utc).isoformat(),))
            columns = {r['name'] for r in connection.execute(
                'PRAGMA table_info(sensor_packet_history)'
            )}
            if 'ingest_channel' not in columns:
                connection.execute("""
                    ALTER TABLE sensor_packet_history
                    ADD COLUMN ingest_channel TEXT NOT NULL DEFAULT 'unspecified'
                """)
            connection.execute("""
                INSERT OR IGNORE INTO schema_migrations
                    (version, applied_at, description)
                VALUES (4, ?, 'Ingestion route provenance for sensor packets')
            """, (datetime.now(timezone.utc).isoformat(),))
            for column in ('radiation_source', 'environment', 'measurement_basis'):
                if column not in columns:
                    connection.execute(
                        f'ALTER TABLE sensor_packet_history ADD COLUMN {column} TEXT'
                    )
            connection.execute("""
                INSERT OR IGNORE INTO schema_migrations
                    (version, applied_at, description)
                VALUES (5, ?, 'Radiation origin, environment, measurement basis')
            """, (datetime.now(timezone.utc).isoformat(),))
    finally:
        connection.close()


def packet_fingerprint(packet):
    """Repeatable device-level identity, independent of replay transport.

    A stable packet_id takes priority when supplied. Otherwise exact device,
    sensor, acquisition timestamp, calibration and payload identify a replay.
    Same value at a NEW timestamp is an independent measurement.
    """
    if packet.packet_id is not None:
        key = [packet.sensor, packet.device_id, packet.packet_id]
    else:
        key = [
            packet.sensor,
            packet.device_id,
            packet.timestamp.astimezone(timezone.utc).isoformat(),
            packet.calibration_id,
            packet.data,
        ]
    canonical = json.dumps(key, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def existing_packet_id(database, fingerprint):
    connection = database._connect()
    try:
        row = connection.execute(
            'SELECT reading_id FROM sensor_packet_history WHERE fingerprint = ?',
            (fingerprint,),
        ).fetchone()
        return row['reading_id'] if row else None
    finally:
        connection.close()


def store_packet_metadata(database, reading_id, fingerprint, packet, *, ingest_channel='unspecified'):
    if ingest_channel not in ('unspecified', 'simulation', 'jsonl', 'tcp', 'serial'):
        raise ValueError('Unknown ingestion channel')
    spec = radiation_specification(packet) if packet.sensor in ('radiation', 'radiation_environment') else None
    connection = database._connect()
    try:
        with connection:
            connection.execute('''
                INSERT INTO sensor_packet_history (
                    reading_id, fingerprint, sensor, device_id, origin,
                    calibration_id, packet_id, particle_type, count_mode,
                    dose_mode, interval_seconds, ingest_channel,
                    radiation_source, environment, measurement_basis
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                reading_id, fingerprint, packet.sensor, packet.device_id,
                packet.origin, packet.calibration_id, packet.packet_id,
                None, None, None, None, ingest_channel,
                spec.radiation_source if spec else None,
                spec.environment if spec else None,
                spec.measurement_basis if spec else None,
            ))
    finally:
        connection.close()


def metadata_by_reading(database, reading_id):
    connection = database._connect()
    try:
        row = connection.execute(
            'SELECT * FROM sensor_packet_history WHERE reading_id = ?',
            (reading_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()
