
# Made in cooperation with ChatGPT
# File: src/astro_health/database.py

import math
import sqlite3

from datetime import datetime, timezone
from pathlib import Path

from astro_health.models import MeasurementValue, Reading
from astro_health.validation import validate_reading


class Database:
    """SQLite storage for health readings."""

    SCHEMA_VERSION = 1

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with foreign keys enabled."""
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        """Create the database and initial schema if necessary."""
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = self._connect()

        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT,
                    source TEXT,
                    mission_day INTEGER,
                    quality TEXT NOT NULL
                        CHECK (
                            quality IN (
                                'unassessed',
                                'ok',
                                'suspect',
                                'invalid'
                            )
                        ),
                    quality_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS measurement_values (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reading_id INTEGER NOT NULL,
                    measurement_type TEXT,
                    value REAL,
                    unit TEXT,
                    FOREIGN KEY (reading_id)
                        REFERENCES readings(id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS
                    idx_measurement_values_reading_id
                    ON measurement_values(reading_id);

                CREATE INDEX IF NOT EXISTS
                    idx_readings_timestamp
                    ON readings(timestamp_utc);
                """
            )

            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations
                    (version, applied_at, description)
                VALUES (?, ?, ?)
                """,
                (
                    self.SCHEMA_VERSION,
                    datetime.now(timezone.utc).isoformat(),
                    "Initial database schema",
                ),
            )

            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _prepare_value(value):
        """Convert unusual invalid values to SQLite-compatible data."""
        if value is None:
            return None

        if isinstance(value, bool):
            return str(value)

        if isinstance(value, (int, float)):
            if not math.isfinite(value):
                return repr(value)
            return value

        return str(value)

    @staticmethod
    def _prepare_text(value):
        """Prepare text fields, preserving None."""
        if value is None:
            return None

        if isinstance(value, str):
            return value

        return str(value)

    def save_reading(self, reading: Reading) -> int:
        """Validate and append one reading to SQLite."""
        result = validate_reading(reading)
        validated = result.reading

        timestamp = validated.timestamp

        if isinstance(timestamp, datetime):
            if (
                timestamp.tzinfo is not None
                and timestamp.utcoffset() is not None
            ):
                timestamp = timestamp.astimezone(timezone.utc)

            timestamp_text = timestamp.isoformat()
        else:
            timestamp_text = self._prepare_text(timestamp)

        connection = self._connect()

        try:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO readings (
                        timestamp_utc,
                        source,
                        mission_day,
                        quality,
                        quality_reason
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp_text,
                        self._prepare_text(validated.source),
                        self._prepare_value(validated.mission_day),
                        validated.quality,
                        validated.quality_reason,
                    ),
                )

                reading_id = cursor.lastrowid

                if isinstance(validated.measurements, tuple):
                    measurements = validated.measurements
                else:
                    measurements = ()

                for measurement in measurements:
                    if not isinstance(
                        measurement,
                        MeasurementValue,
                    ):
                        continue

                    connection.execute(
                        """
                        INSERT INTO measurement_values (
                            reading_id,
                            measurement_type,
                            value,
                            unit
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            reading_id,
                            self._prepare_text(
                                measurement.measurement_type
                            ),
                            self._prepare_value(
                                measurement.value
                            ),
                            self._prepare_text(
                                measurement.unit
                            ),
                        ),
                    )

            return reading_id
        finally:
            connection.close()

    def get_reading(self, reading_id: int) -> Reading | None:
        """Retrieve one reading and all its measurements."""
        connection = self._connect()

        try:
            row = connection.execute(
                """
                SELECT
                    id,
                    timestamp_utc,
                    source,
                    mission_day,
                    quality,
                    quality_reason
                FROM readings
                WHERE id = ?
                """,
                (reading_id,),
            ).fetchone()

            if row is None:
                return None

            measurement_rows = connection.execute(
                """
                SELECT measurement_type, value, unit
                FROM measurement_values
                WHERE reading_id = ?
                ORDER BY id
                """,
                (reading_id,),
            ).fetchall()
        finally:
            connection.close()

        measurements = tuple(
            MeasurementValue(
                measurement_type=item["measurement_type"],
                value=item["value"],
                unit=item["unit"],
            )
            for item in measurement_rows
        )

        timestamp_text = row["timestamp_utc"]

        try:
            timestamp = datetime.fromisoformat(timestamp_text)
        except (TypeError, ValueError):
            timestamp = timestamp_text

        return Reading(
            id=row["id"],
            source=row["source"],
            measurements=measurements,
            timestamp=timestamp,
            mission_day=row["mission_day"],
            quality=row["quality"],
            quality_reason=row["quality_reason"],
        )

    def list_readings(self) -> list[Reading]:
        """Return saved readings, newest saved first."""
        connection = self._connect()

        try:
            rows = connection.execute(
                """
                SELECT id
                FROM readings
                ORDER BY id DESC
                """
            ).fetchall()
        finally:
            connection.close()

        readings = []

        for row in rows:
            reading = self.get_reading(row["id"])

            if reading is not None:
                readings.append(reading)

        return readings
