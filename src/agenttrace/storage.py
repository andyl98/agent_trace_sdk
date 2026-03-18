"""SQLite storage layer for agenttrace events."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from ._utils import safe_json_dumps
from .types import Event

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id    TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    trace_id    TEXT,
    span_id     TEXT,
    parent_id   TEXT,
    name        TEXT NOT NULL,
    kind        TEXT,
    status      TEXT,
    duration_ms REAL,
    meta        TEXT,
    service_name TEXT,
    snapshot_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(event_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id);
CREATE INDEX IF NOT EXISTS idx_events_span ON events(span_id);
CREATE INDEX IF NOT EXISTS idx_events_duration ON events(event_type, duration_ms);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);
CREATE INDEX IF NOT EXISTS idx_events_snapshot ON events(snapshot_id);

CREATE VIEW IF NOT EXISTS v_traces AS
    SELECT event_id, trace_id, name, kind, status, duration_ms,
           timestamp AS started_at, meta, service_name, snapshot_id
    FROM events WHERE event_type = 'trace';

CREATE VIEW IF NOT EXISTS v_spans AS
    SELECT event_id, span_id, trace_id, parent_id, name, kind, status,
           duration_ms, timestamp AS started_at, meta
    FROM events WHERE event_type = 'span';

CREATE VIEW IF NOT EXISTS v_errors AS
    SELECT event_id, trace_id, span_id, timestamp, name AS error_type,
           status AS level, meta,
           json_extract(meta, '$.message') AS message,
           json_extract(meta, '$.stack_trace') AS stack_trace,
           json_extract(meta, '$.fingerprint') AS fingerprint,
           json_extract(meta, '$.status_code') AS status_code
    FROM events WHERE event_type = 'error';

CREATE VIEW IF NOT EXISTS v_metrics AS
    SELECT event_id, name, json_extract(meta, '$.value') AS value,
           json_extract(meta, '$.tags') AS tags, timestamp, snapshot_id
    FROM events WHERE event_type = 'metric';

CREATE VIEW IF NOT EXISTS v_snapshots AS
    SELECT event_id AS snapshot_id, timestamp, meta, service_name
    FROM events WHERE event_type = 'snapshot';
"""


def _deep_merge(base: dict, updates: dict) -> None:
    """Recursively merge updates into base dict in place."""
    for k, v in updates.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


class Storage:
    """SQLite-backed event storage."""

    def __init__(self, db_path: str = ".agenttrace.db") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self._conn = sqlite3.connect(
            self._db_path, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Storage not initialized. Call initialize() first.")
        return self._conn

    # ---- Write ----------------------------------------------------------

    def write_event(self, event: Event) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO events
                   (event_id, event_type, timestamp, trace_id, span_id, parent_id,
                    name, kind, status, duration_ms, meta, service_name, snapshot_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.event_id,
                    event.event_type,
                    event.timestamp,
                    event.trace_id,
                    event.span_id,
                    event.parent_id,
                    event.name,
                    event.kind,
                    event.status,
                    event.duration_ms,
                    safe_json_dumps(event.meta),
                    event.service_name,
                    event.snapshot_id,
                ),
            )
            self.conn.commit()

    def write_events(self, events: list[Event]) -> None:
        with self._lock:
            self.conn.executemany(
                """INSERT INTO events
                   (event_id, event_type, timestamp, trace_id, span_id, parent_id,
                    name, kind, status, duration_ms, meta, service_name, snapshot_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        e.event_id, e.event_type, e.timestamp, e.trace_id,
                        e.span_id, e.parent_id, e.name, e.kind, e.status,
                        e.duration_ms, safe_json_dumps(e.meta), e.service_name,
                        e.snapshot_id,
                    )
                    for e in events
                ],
            )
            self.conn.commit()

    def update_event(self, event_id: str, **fields: Any) -> None:
        """Update specific columns on an existing event."""
        if not fields:
            return
        with self._lock:
            # Handle meta merging specially (deep merge)
            if "meta" in fields and isinstance(fields["meta"], dict):
                row = self.conn.execute(
                    "SELECT meta FROM events WHERE event_id = ?", (event_id,)
                ).fetchone()
                if row and row["meta"]:
                    existing = json.loads(row["meta"])
                    _deep_merge(existing, fields["meta"])
                    fields["meta"] = safe_json_dumps(existing)
                else:
                    fields["meta"] = safe_json_dumps(fields["meta"])

            set_clause = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [event_id]
            self.conn.execute(
                f"UPDATE events SET {set_clause} WHERE event_id = ?", values
            )
            self.conn.commit()

    def purge_old(self, retention_days: int) -> int:
        with self._lock:
            cursor = self.conn.execute(
                "DELETE FROM events WHERE timestamp < datetime('now', ?)",
                (f"-{retention_days} days",),
            )
            self.conn.commit()
            return cursor.rowcount

    # ---- Read -----------------------------------------------------------

    def query_events(
        self,
        event_type: str | None = None,
        trace_id: str | None = None,
        name: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        since: str | None = None,
        until: str | None = None,
        min_duration: float | None = None,
        order_by: str = "timestamp",
        desc: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Flexible query over the events table."""
        conditions: list[str] = []
        params: list[Any] = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if trace_id:
            conditions.append("trace_id = ?")
            params.append(trace_id)
        if name:
            conditions.append("name LIKE ?")
            params.append(f"%{name}%")
        if kind:
            conditions.append("kind = ?")
            params.append(kind)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)
        if min_duration is not None:
            conditions.append("duration_ms >= ?")
            params.append(min_duration)

        where = " AND ".join(conditions) if conditions else "1=1"
        direction = "DESC" if desc else "ASC"

        # Validate order_by to prevent injection
        allowed_columns = {
            "timestamp", "duration_ms", "name", "kind", "status", "event_type"
        }
        if order_by not in allowed_columns:
            order_by = "timestamp"

        sql = f"SELECT * FROM events WHERE {where} ORDER BY {order_by} {direction} LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self.conn.execute(sql, tuple(params)).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def execute_sql(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Raw SQL escape hatch."""
        with self._lock:
            rows = self.conn.execute(sql, tuple(params)).fetchall()
            return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        if d.get("meta") and isinstance(d["meta"], str):
            try:
                d["meta"] = json.loads(d["meta"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
