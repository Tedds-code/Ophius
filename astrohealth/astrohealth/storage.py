"""Durable profiles, daily aggregates, laboratory reports and warning events.

Normal raw sensor samples deliberately have no table: their short-lived buffer
belongs to the monitor. A source partition keeps simulation and observations
separate even when they share a profile and calendar day.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    """A single protected SQLite connection with immediately durable events."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        with self.connection:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    astronaut_id TEXT PRIMARY KEY,
                    document TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS anchors (
                    astronaut_id TEXT NOT NULL REFERENCES profiles(astronaut_id),
                    source TEXT NOT NULL,
                    first_timestamp TEXT NOT NULL,
                    PRIMARY KEY (astronaut_id, source)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    astronaut_id TEXT NOT NULL REFERENCES profiles(astronaut_id),
                    day TEXT NOT NULL,
                    source TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    UNIQUE (astronaut_id, day, source)
                );
                CREATE TABLE IF NOT EXISTS daily (
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    measurement_key TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    statistics TEXT NOT NULL,
                    PRIMARY KEY (session_id, measurement_key, unit)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    astronaut_id TEXT NOT NULL REFERENCES profiles(astronaut_id),
                    session_id TEXT REFERENCES sessions(id),
                    kind TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    acknowledged INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_by_profile
                    ON events(astronaut_id, timestamp);
                CREATE TABLE IF NOT EXISTS laboratory_reports (
                    astronaut_id TEXT NOT NULL REFERENCES profiles(astronaut_id),
                    id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    report TEXT NOT NULL,
                    PRIMARY KEY (astronaut_id, id)
                );
            """)
        # Preserve old-unit summaries when a replacement catalog changes units.
        columns = self.connection.execute('PRAGMA table_info(daily)').fetchall()
        primary_key = [row['name'] for row in sorted(columns, key=lambda row: row['pk']) if row['pk']]
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            if primary_key == ['session_id', 'measurement_key']:
                self.connection.execute('ALTER TABLE daily RENAME TO daily_v1')
                self.connection.execute('''CREATE TABLE daily (
                    session_id TEXT NOT NULL REFERENCES sessions(id), measurement_key TEXT NOT NULL,
                    unit TEXT NOT NULL, statistics TEXT NOT NULL,
                    PRIMARY KEY(session_id, measurement_key, unit))''')
                self.connection.execute('INSERT INTO daily SELECT * FROM daily_v1')
                self.connection.execute('DROP TABLE daily_v1')
            self.connection.execute('PRAGMA user_version = 2')

    def load_profiles(self) -> list[dict]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT document FROM profiles ORDER BY astronaut_id"
            ).fetchall()
            return [json.loads(row["document"]) for row in rows]

    def save_profile(self, profile: dict) -> None:
        encoded = _json(profile)
        aid = profile["astronaut_id"]
        if not isinstance(aid, str) or not aid:
            raise ValueError("astronaut_id must be a nonempty string")
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO profiles(astronaut_id, document, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(astronaut_id) DO UPDATE SET document=excluded.document, "
                "updated_at=excluded.updated_at",
                (aid, encoded, _now()),
            )

    def anchor(self, aid: str, iso_timestamp: str, source: str = "observed") -> str:
        """Set once per source partition; later imports do not move day one."""
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO anchors(astronaut_id, source, first_timestamp) "
                "VALUES (?, ?, ?)",
                (aid, source, iso_timestamp),
            )
            row = self.connection.execute(
                "SELECT first_timestamp FROM anchors WHERE astronaut_id=? AND source=?",
                (aid, source),
            ).fetchone()
            return row["first_timestamp"]

    def get_anchor(self, aid: str, source: str = "observed") -> str | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT first_timestamp FROM anchors WHERE astronaut_id=? AND source=?",
                (aid, source),
            ).fetchone()
            return row["first_timestamp"] if row else None

    def session(self, aid: str, day: str, source: str) -> str:
        parsed_day = date.fromisoformat(day)
        day = parsed_day.isoformat()
        sid = uuid.uuid5(uuid.NAMESPACE_URL, f"astrohealth:{aid}:{source}:{day}").hex
        started_at = datetime.combine(parsed_day, datetime.min.time(), timezone.utc).isoformat()
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO sessions(id, astronaut_id, day, source, started_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, aid, day, source, started_at),
            )
            row = self.connection.execute(
                "SELECT id FROM sessions WHERE astronaut_id=? AND day=? AND source=?",
                (aid, day, source),
            ).fetchone()
            return row["id"]

    def save_daily(self, session_id: str, key: str, unit: str, stats: dict) -> None:
        encoded = _json(stats)
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO daily(session_id, measurement_key, unit, statistics) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id, measurement_key, unit) DO UPDATE SET "
                "unit=excluded.unit, statistics=excluded.statistics",
                (session_id, key, unit, encoded),
            )

    @staticmethod
    def _event(row: sqlite3.Row) -> dict:
        # Identity and acknowledgement must never be overwritten by payload keys.
        return {
            **json.loads(row["payload"]),
            "id": row["id"],
            "session_id": row["session_id"],
            "kind": row["kind"],
            "timestamp": row["timestamp"],
            "acknowledged": bool(row["acknowledged"]),
        }

    def add_event(self, aid: str, session_id: str | None, kind: str, payload: dict) -> dict:
        encoded = _json(payload)
        eid = uuid.uuid4().hex
        timestamp = payload.get("timestamp") or _now()
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO events(id, astronaut_id, session_id, kind, timestamp, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, aid, session_id, kind, timestamp, encoded),
            )
            row = self.connection.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
            return self._event(row)

    def acknowledge(self, aid: str, event_id: str) -> bool:
        with self.lock, self.connection:
            cursor = self.connection.execute(
                "UPDATE events SET acknowledged=1 WHERE astronaut_id=? AND id=?",
                (aid, event_id),
            )
            return cursor.rowcount > 0

    def events(self, aid: str) -> list[dict]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM events WHERE astronaut_id=? ORDER BY timestamp, rowid", (aid,)
            ).fetchall()
            return [self._event(row) for row in rows]

    def save_lab(self, aid: str, source: str, report: dict) -> str:
        rid = report.get("report_id") or uuid.uuid4().hex
        if not isinstance(rid, str) or not rid:
            raise ValueError("report_id must be a nonempty string")
        encoded = _json(report)
        timestamp = report.get("timestamp") or _now()
        with self.lock, self.connection:
            try:
                self.connection.execute(
                    "INSERT INTO laboratory_reports(astronaut_id,id,source,timestamp,report) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (aid, rid, source, timestamp, encoded),
                )
            except sqlite3.IntegrityError as exc:
                if self.has_lab(aid, rid):
                    raise ValueError(f"Laboratory report {rid!r} was already imported") from exc
                raise
        return rid

    def has_lab(self, aid: str, report_id: str) -> bool:
        with self.lock:
            return self.connection.execute(
                "SELECT 1 FROM laboratory_reports WHERE astronaut_id=? AND id=?", (aid, report_id)
            ).fetchone() is not None

    def labs(self, aid: str) -> list[dict]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM laboratory_reports WHERE astronaut_id=? ORDER BY timestamp, rowid", (aid,)
            ).fetchall()
            return [
                {**json.loads(row["report"]), "id": row["id"], "source": row["source"]}
                for row in rows
            ]

    def all_daily(self, aid: str) -> list[dict]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT d.*, s.day, s.source FROM daily d "
                "JOIN sessions s ON s.id=d.session_id "
                "WHERE s.astronaut_id=? ORDER BY s.day, s.source, d.measurement_key", (aid,)
            ).fetchall()
            return [
                {**json.loads(row["statistics"]), "session_id": row["session_id"],
                 "day": row["day"], "source": row["source"], "key": row["measurement_key"],
                 "unit": row["unit"]}
                for row in rows
            ]

    def history(self, aid: str) -> dict:
        with self.lock:
            sessions = [dict(row) for row in self.connection.execute(
                "SELECT * FROM sessions WHERE astronaut_id=? ORDER BY day, source", (aid,)
            ).fetchall()]
            return {"sessions": sessions, "daily": self.all_daily(aid),
                    "events": self.events(aid), "lab_reports": self.labs(aid)}

    def close(self) -> None:
        with self.lock:
            self.connection.close()
