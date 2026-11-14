# Made in cooperation with ChatGPT
# File: src/astro_health/session_store.py
"""Durable health-check sessions over the existing append-only readings.

A session groups individual readings without copying or rewriting them.
Every reading remains available by its original ID. No medical thresholds
are used to choose summary values: the newest non-invalid stored observation
per fixed field is shown, with no claims about accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from astro_health.fixed_tests import FIXED_TESTS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class HealthSession:
    id: int
    started_at: str
    ended_at: str | None
    status: str
    reading_count: int


@dataclass(frozen=True)
class SummaryValue:
    measurement_type: str
    value: float
    unit: str
    reading_id: int
    timestamp: datetime
    source: str


class SessionStore:
    """Session metadata and reading-to-session associations in the same DB."""

    def __init__(self, database):
        self.database = database

    def initialize(self) -> None:
        """Apply additive schema version 2; preserve every existing reading."""
        # Call the existing v1 initializer so the legacy schema always exists.
        self.database.initialize()
        connection = self.database._connect()
        try:
            with connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS health_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        status TEXT NOT NULL CHECK (
                            status IN ('active', 'completed', 'interrupted')
                        )
                    )"""
                )
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS session_readings (
                        reading_id INTEGER PRIMARY KEY,
                        session_id INTEGER NOT NULL,
                        FOREIGN KEY (reading_id) REFERENCES readings(id)
                            ON DELETE RESTRICT,
                        FOREIGN KEY (session_id) REFERENCES health_sessions(id)
                            ON DELETE RESTRICT
                    )"""
                )
                connection.execute(
                    """CREATE INDEX IF NOT EXISTS idx_session_readings_session
                       ON session_readings(session_id)"""
                )
                connection.execute(
                    """INSERT OR IGNORE INTO schema_migrations
                        (version, applied_at, description)
                        VALUES (2, ?, 'Health-check sessions and reading links')""",
                    (_now(),),
                )
        finally:
            connection.close()
        from astro_health.sensor_history import ensure_sensor_history
        ensure_sensor_history(self.database)

    def recover_interrupted(self) -> int:
        """Mark previously active sessions interrupted after an unclean exit.

        Run once during startup, before creating this process's new session.
        Previously committed readings remain intact.
        """
        connection = self.database._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """UPDATE health_sessions SET status = 'interrupted',
                       ended_at = ? WHERE status = 'active'""",
                    (_now(),),
                )
                return cursor.rowcount
        finally:
            connection.close()

    def start(self) -> int:
        connection = self.database._connect()
        try:
            with connection:
                cursor = connection.execute(
                    "INSERT INTO health_sessions(started_at, status) VALUES (?, 'active')",
                    (_now(),),
                )
                return cursor.lastrowid
        finally:
            connection.close()

    def finish(self, session_id: int, *, interrupted: bool = False) -> None:
        status = 'interrupted' if interrupted else 'completed'
        connection = self.database._connect()
        try:
            with connection:
                connection.execute(
                    """UPDATE health_sessions SET ended_at = ?, status = ?
                       WHERE id = ? AND status = 'active'""",
                    (_now(), status, session_id),
                )
        finally:
            connection.close()

    def attach_reading(self, session_id: int, reading_id: int) -> None:
        """Attach an already committed reading; never move it to a new session."""
        connection = self.database._connect()
        try:
            with connection:
                row = connection.execute(
                    'SELECT status FROM health_sessions WHERE id = ?',
                    (session_id,),
                ).fetchone()
                if row is None or row['status'] != 'active':
                    raise ValueError('Cannot attach to a non-active session')
                connection.execute(
                    'INSERT INTO session_readings(session_id, reading_id) VALUES (?, ?)',
                    (session_id, reading_id),
                )
        finally:
            connection.close()

    def list_sessions(self) -> list[HealthSession]:
        connection = self.database._connect()
        try:
            rows = connection.execute(
                """SELECT s.id, s.started_at, s.ended_at, s.status,
                          COUNT(sr.reading_id) AS reading_count
                   FROM health_sessions s
                   LEFT JOIN session_readings sr ON sr.session_id = s.id
                   GROUP BY s.id
                   ORDER BY s.id DESC"""
            ).fetchall()
            return [HealthSession(**dict(row)) for row in rows]
        finally:
            connection.close()

    def get_session(self, session_id: int) -> HealthSession | None:
        connection = self.database._connect()
        try:
            row = connection.execute(
                """SELECT s.id, s.started_at, s.ended_at, s.status,
                          COUNT(sr.reading_id) AS reading_count
                   FROM health_sessions s
                   LEFT JOIN session_readings sr ON sr.session_id = s.id
                   WHERE s.id = ? GROUP BY s.id""",
                (session_id,),
            ).fetchone()
            return HealthSession(**dict(row)) if row is not None else None
        finally:
            connection.close()

    def readings_for_session(self, session_id: int):
        connection = self.database._connect()
        try:
            rows = connection.execute(
                """SELECT reading_id FROM session_readings
                   WHERE session_id = ? ORDER BY reading_id""",
                (session_id,),
            ).fetchall()
        finally:
            connection.close()
        return [self.database.get_reading(row['reading_id']) for row in rows]

    def summary(self, session_id: int) -> dict[str, SummaryValue]:
        """Newest complete, non-invalid observation for each predefined test.

        All fields belonging to one test (e.g., systolic and diastolic BP)
        must come from the SAME reading. No clinical accuracy is inferred.
        """
        selected: dict[str, SummaryValue] = {}
        completed_tests: set[str] = set()
        readings = self.readings_for_session(session_id)
        # Most recently saved first: device timestamps are not always reliable.
        for reading in reversed(readings):
            if reading is None or reading.quality in ('invalid', 'suspect'):
                continue
            candidates = {m.measurement_type: m for m in reading.measurements}
            for test in FIXED_TESTS:
                if test.test_id in completed_tests:
                    continue
                if not all(
                    field.measurement_type in candidates
                    and candidates[field.measurement_type].unit == field.unit
                    for field in test.fields
                ):
                    continue
                completed_tests.add(test.test_id)
                for field in test.fields:
                    measurement = candidates[field.measurement_type]
                    selected[field.measurement_type] = SummaryValue(
                        field.measurement_type, measurement.value,
                        measurement.unit, reading.id, reading.timestamp,
                        reading.source,
                    )
            if len(completed_tests) == len(FIXED_TESTS):
                break
        return selected

    def mission_day_now(self) -> int | None:
        """UTC calendar day since first saved reading (day 1); None if empty."""
        connection = self.database._connect()
        try:
            row = connection.execute(
                "SELECT timestamp_utc FROM readings ORDER BY id ASC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        if not row or not row['timestamp_utc']:
            return None
        try:
            first = datetime.fromisoformat(row['timestamp_utc'])
            if first.tzinfo is None or first.utcoffset() is None:
                return None
        except (ValueError, TypeError):
            return None
        start = first.astimezone(timezone.utc).date()
        return max(1, (datetime.now(timezone.utc).date() - start).days + 1)

    def nasa_radiation_report(self, *, session_id: int | None = None) -> dict:
        """Separate NASA-standard-oriented reporting; no automatic risk verdict."""
        from astro_health.radiation_requirements import summarize_nasa_radiation
        return summarize_nasa_radiation(self.database, session_id=session_id)

