# Made in cooperation with ChatGPT
# File: src/astro_health/health_service.py
"""Application service; automatically assigns mission days on recording.

The UTC date of the FIRST SAVED reading anchors mission day 1.  All later
readings use their acquisition UTC date; time spent without program runs still
counts as calendar days.  The stored timestamp is not replaced.
"""

from dataclasses import replace
from datetime import datetime, timezone

from astro_health.database import Database
from astro_health.models import Reading
from astro_health.reading_source import ReadingSource


def _utc_date(timestamp: datetime):
    if not isinstance(timestamp, datetime):
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp.astimezone(timezone.utc).date()


class HealthService:
    """Coordinate sources and SQLite, assigning mission day automatically."""

    def __init__(self, database: Database):
        self.database = database

    def record_from_source(self, source: ReadingSource) -> int:
        if not isinstance(source, ReadingSource):
            raise TypeError("Expected a ReadingSource object.")
        return self.record_reading(source.read())

    def record_reading(self, reading: Reading) -> int:
        if not isinstance(reading, Reading):
            raise TypeError("Expected a Reading object.")

        # First SAVED reading, not the current session, sets the epoch.
        # A timestamp from an imported file is used as provided, in UTC.
        current = _utc_date(reading.timestamp)
        if current is not None:
            connection = self.database._connect()
            try:
                row = connection.execute(
                    "SELECT timestamp_utc FROM readings ORDER BY id ASC LIMIT 1"
                ).fetchone()
            finally:
                connection.close()
            anchor = None
            if row is not None and row["timestamp_utc"]:
                try:
                    anchor = _utc_date(datetime.fromisoformat(row["timestamp_utc"]))
                except (ValueError, TypeError):
                    pass
            # Imported readings predating the first saved reading cannot
            # have a positive calendar offset: clamp to day 1 and keep the
            # original timestamp for subsequent data review.
            day = max(1, (current - (anchor or current)).days + 1)
            reading = replace(reading, mission_day=day)
        return self.database.save_reading(reading)

    def get_reading(self, reading_id: int) -> Reading | None:
        if isinstance(reading_id, bool) or not isinstance(reading_id, int):
            raise TypeError("Reading ID must be an integer.")
        if reading_id <= 0:
            raise ValueError("Reading ID must be greater than zero.")
        return self.database.get_reading(reading_id)

    def list_readings(self) -> list[Reading]:
        return self.database.list_readings()
