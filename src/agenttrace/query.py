"""Agent-facing query API over the agenttrace event store."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ._utils import PST
from typing import Any

from .storage import Storage


def _since_to_iso(since: str | None) -> str | None:
    """Convert a relative time string like '1h', '24h', '7d' to ISO timestamp."""
    if since is None:
        return None
    # Already ISO?
    if "T" in since or "-" in since:
        return since
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    suffix = since[-1]
    if suffix in units:
        try:
            amount = int(since[:-1])
        except ValueError:
            return since
        delta = timedelta(**{units[suffix]: amount})
        return (datetime.now(PST) - delta).isoformat()
    return since


class QueryAPI:
    """High-level query interface for agent consumption. All methods return JSON-serializable dicts/lists."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    # ---- Traces -------------------------------------------------------

    def find_traces(
        self,
        *,
        path: str | None = None,
        method: str | None = None,
        status: str | None = None,
        min_duration: float | None = None,
        since: str | None = None,
        until: str | None = None,
        sort: str = "timestamp",
        desc: bool = True,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find traces matching filters."""
        conditions: list[str] = ["event_type = 'trace'"]
        params: list[Any] = []

        if path:
            conditions.append("json_extract(meta, '$.http.path') LIKE ?")
            params.append(f"%{path}%")
        if method:
            conditions.append("json_extract(meta, '$.http.method') = ?")
            params.append(method.upper())
        if status:
            conditions.append("status = ?")
            params.append(status)
        if min_duration is not None:
            conditions.append("duration_ms >= ?")
            params.append(min_duration)
        since_iso = _since_to_iso(since)
        if since_iso:
            conditions.append("timestamp >= ?")
            params.append(since_iso)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)

        allowed_sort = {"timestamp", "duration_ms", "name"}
        col = sort if sort in allowed_sort else "timestamp"
        direction = "DESC" if desc else "ASC"

        sql = (
            f"SELECT event_id, trace_id, name, kind, status, duration_ms, "
            f"timestamp AS started_at, meta, service_name, snapshot_id "
            f"FROM events WHERE {' AND '.join(conditions)} "
            f"ORDER BY {col} {direction} LIMIT ?"
        )
        params.append(limit)
        return self._storage.execute_sql(sql, tuple(params))

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """Get a single trace with its full span tree."""
        traces = self._storage.execute_sql(
            "SELECT * FROM events WHERE event_type = 'trace' AND trace_id = ?",
            (trace_id,),
        )
        if not traces:
            return None
        trace = traces[0]

        spans = self._storage.execute_sql(
            "SELECT * FROM events WHERE event_type = 'span' AND trace_id = ? "
            "ORDER BY timestamp ASC",
            (trace_id,),
        )

        errors = self._storage.execute_sql(
            "SELECT * FROM events WHERE event_type = 'error' AND trace_id = ? "
            "ORDER BY timestamp ASC",
            (trace_id,),
        )

        trace["spans"] = spans
        trace["errors"] = errors
        return trace

    # ---- Spans --------------------------------------------------------

    def find_spans(
        self,
        *,
        trace_id: str | None = None,
        kind: str | None = None,
        path: str | None = None,
        semantic_type: str | None = None,
        semantic_name: str | None = None,
        min_duration: float | None = None,
        name: str | None = None,
        since: str | None = None,
        sort: str = "duration_ms",
        desc: bool = True,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find spans matching filters."""
        conditions: list[str] = ["event_type = 'span'"]
        params: list[Any] = []

        if trace_id:
            conditions.append("trace_id = ?")
            params.append(trace_id)
        if kind:
            conditions.append("kind = ?")
            params.append(kind)
        if path:
            conditions.append(
                "trace_id IN (SELECT trace_id FROM events WHERE event_type = 'trace' "
                "AND json_extract(meta, '$.http.path') LIKE ?)"
            )
            params.append(f"%{path}%")
        if semantic_type:
            conditions.append("json_extract(meta, '$.semantic.type') = ?")
            params.append(semantic_type)
        if semantic_name:
            conditions.append(
                "COALESCE("
                "json_extract(meta, '$.semantic.intent'), "
                "json_extract(meta, '$.semantic.decision'), "
                "json_extract(meta, '$.semantic.name')"
                ") LIKE ?"
            )
            params.append(f"%{semantic_name}%")
        if min_duration is not None:
            conditions.append("duration_ms >= ?")
            params.append(min_duration)
        if name:
            conditions.append("name LIKE ?")
            params.append(f"%{name}%")
        since_iso = _since_to_iso(since)
        if since_iso:
            conditions.append("timestamp >= ?")
            params.append(since_iso)

        allowed_sort = {"timestamp", "duration_ms", "name"}
        col = sort if sort in allowed_sort else "duration_ms"
        direction = "DESC" if desc else "ASC"

        sql = (
            f"SELECT * FROM events WHERE {' AND '.join(conditions)} "
            f"ORDER BY {col} {direction} LIMIT ?"
        )
        params.append(limit)
        return self._storage.execute_sql(sql, tuple(params))

    def span_stats(
        self,
        *,
        kind: str | None = None,
        name: str | None = None,
        path: str | None = None,
        semantic_type: str | None = None,
        semantic_name: str | None = None,
        since: str | None = "24h",
        bucket: str | None = None,
    ) -> dict[str, Any]:
        """Compute duration stats for spans, including semantic spans."""
        conditions = ["event_type = 'span'"]
        params: list[Any] = []

        if kind:
            conditions.append("kind = ?")
            params.append(kind)
        if name:
            conditions.append("name LIKE ?")
            params.append(f"%{name}%")
        if path:
            conditions.append(
                "trace_id IN (SELECT trace_id FROM events WHERE event_type = 'trace' "
                "AND json_extract(meta, '$.http.path') LIKE ?)"
            )
            params.append(f"%{path}%")
        if semantic_type:
            conditions.append("json_extract(meta, '$.semantic.type') = ?")
            params.append(semantic_type)
        if semantic_name:
            conditions.append(
                "COALESCE("
                "json_extract(meta, '$.semantic.intent'), "
                "json_extract(meta, '$.semantic.decision'), "
                "json_extract(meta, '$.semantic.name')"
                ") LIKE ?"
            )
            params.append(f"%{semantic_name}%")

        since_iso = _since_to_iso(since)
        if since_iso:
            conditions.append("timestamp >= ?")
            params.append(since_iso)

        where = " AND ".join(conditions)
        summary = self._storage.execute_sql(
            f"SELECT "
            f"count(*) AS total, "
            f"avg(duration_ms) AS avg_duration_ms, "
            f"max(duration_ms) AS max_duration_ms, "
            f"min(duration_ms) AS min_duration_ms "
            f"FROM events WHERE {where}",
            tuple(params),
        )

        result = summary[0] if summary else {}
        self._add_duration_percentiles(result, where, params)

        if bucket and result.get("total", 0) > 0:
            bucket_seconds = _parse_bucket(bucket)
            buckets = self._storage.execute_sql(
                f"SELECT "
                f"strftime('%s', timestamp) / ? * ? AS bucket_ts, "
                f"count(*) AS total, "
                f"avg(duration_ms) AS avg_duration_ms, "
                f"max(duration_ms) AS max_duration_ms "
                f"FROM events WHERE {where} "
                f"GROUP BY bucket_ts ORDER BY bucket_ts",
                (bucket_seconds, bucket_seconds, *params),
            )
            for b in buckets:
                if b.get("bucket_ts") is not None:
                    b["bucket_time"] = datetime.fromtimestamp(
                        int(b["bucket_ts"]), tz=PST
                    ).isoformat()
            result["buckets"] = buckets

        return result

    # ---- Errors -------------------------------------------------------

    def group_errors(
        self,
        *,
        group_by: str = "fingerprint",
        path: str | None = None,
        since: str | None = None,
        sort: str = "count",
        desc: bool = True,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Group errors by a dimension (fingerprint, status_code, error_type)."""
        valid_groups = {
            "fingerprint": "json_extract(meta, '$.fingerprint')",
            "status_code": "json_extract(meta, '$.status_code')",
            "error_type": "name",
        }
        group_expr = valid_groups.get(group_by, valid_groups["fingerprint"])

        conditions = ["event_type = 'error'"]
        params: list[Any] = []

        if path:
            # Join through trace to get path
            conditions.append(
                "trace_id IN (SELECT trace_id FROM events WHERE event_type = 'trace' "
                "AND json_extract(meta, '$.http.path') LIKE ?)"
            )
            params.append(f"%{path}%")
        since_iso = _since_to_iso(since)
        if since_iso:
            conditions.append("timestamp >= ?")
            params.append(since_iso)

        sort_col = "cnt" if sort == "count" else "latest"
        direction = "DESC" if desc else "ASC"

        sql = (
            f"SELECT {group_expr} AS group_key, "
            f"count(*) AS cnt, "
            f"min(timestamp) AS first_seen, "
            f"max(timestamp) AS latest, "
            f"json_extract(meta, '$.message') AS sample_message "
            f"FROM events WHERE {' AND '.join(conditions)} "
            f"GROUP BY group_key "
            f"ORDER BY {sort_col} {direction} LIMIT ?"
        )
        params.append(limit)
        return self._storage.execute_sql(sql, tuple(params))

    def get_error_examples(
        self,
        fingerprint: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get example error events for a given fingerprint."""
        return self._storage.execute_sql(
            "SELECT * FROM events WHERE event_type = 'error' "
            "AND json_extract(meta, '$.fingerprint') = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (fingerprint, limit),
        )

    # ---- Stats --------------------------------------------------------

    def stats(
        self,
        path: str,
        *,
        since: str | None = "24h",
        bucket: str | None = None,
    ) -> dict[str, Any]:
        """Compute success/error rate for an endpoint."""
        conditions = [
            "event_type = 'trace'",
            "json_extract(meta, '$.http.path') LIKE ?",
        ]
        params: list[Any] = [f"%{path}%"]

        since_iso = _since_to_iso(since)
        if since_iso:
            conditions.append("timestamp >= ?")
            params.append(since_iso)

        where = " AND ".join(conditions)

        summary = self._storage.execute_sql(
            f"SELECT "
            f"count(*) AS total, "
            f"sum(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS success, "
            f"sum(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors, "
            f"avg(duration_ms) AS avg_duration_ms, "
            f"max(duration_ms) AS max_duration_ms, "
            f"min(duration_ms) AS min_duration_ms "
            f"FROM events WHERE {where}",
            tuple(params),
        )

        result = summary[0] if summary else {}
        self._add_duration_percentiles(result, where, params)
        total = result.get("total", 0)
        if total > 0:
            result["error_rate"] = round(
                (result.get("errors", 0) or 0) / total * 100, 2
            )
            result["success_rate"] = round(
                (result.get("success", 0) or 0) / total * 100, 2
            )
        else:
            result["error_rate"] = 0.0
            result["success_rate"] = 0.0

        # Optional time bucketing
        if bucket and total > 0:
            bucket_seconds = _parse_bucket(bucket)
            buckets = self._storage.execute_sql(
                f"SELECT "
                f"strftime('%s', timestamp) / ? * ? AS bucket_ts, "
                f"count(*) AS total, "
                f"sum(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors "
                f"FROM events WHERE {where} "
                f"GROUP BY bucket_ts ORDER BY bucket_ts",
                (*params, bucket_seconds, bucket_seconds),
            )
            # Convert epoch back to ISO for readability
            for b in buckets:
                if b.get("bucket_ts") is not None:
                    b["bucket_time"] = datetime.fromtimestamp(
                        int(b["bucket_ts"]), tz=PST
                    ).isoformat()
            result["buckets"] = buckets

        return result

    # ---- Snapshots ----------------------------------------------------

    def list_snapshots(
        self,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """List deployment snapshots, most recent first."""
        return self._storage.execute_sql(
            "SELECT event_id AS snapshot_id, timestamp, meta, service_name "
            "FROM events WHERE event_type = 'snapshot' "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )

    def diff_snapshots(
        self, left_id: str, right_id: str
    ) -> dict[str, Any]:
        """Diff two deployment snapshots."""
        left = self._storage.execute_sql(
            "SELECT * FROM events WHERE event_id = ? AND event_type = 'snapshot'",
            (left_id,),
        )
        right = self._storage.execute_sql(
            "SELECT * FROM events WHERE event_id = ? AND event_type = 'snapshot'",
            (right_id,),
        )
        if not left or not right:
            return {"error": "One or both snapshots not found"}

        lm = left[0].get("meta", {})
        rm = right[0].get("meta", {})

        result: dict[str, Any] = {
            "left": {"snapshot_id": left_id, "timestamp": left[0]["timestamp"]},
            "right": {"snapshot_id": right_id, "timestamp": right[0]["timestamp"]},
        }

        # Diff dependencies
        ldeps = lm.get("dependencies", {})
        rdeps = rm.get("dependencies", {})
        dep_changes: dict[str, Any] = {}
        all_keys = set(ldeps) | set(rdeps)
        for k in sorted(all_keys):
            lv, rv = ldeps.get(k), rdeps.get(k)
            if lv != rv:
                dep_changes[k] = {"from": lv, "to": rv}
        result["dependencies_changed"] = dep_changes

        # Diff env vars
        lenv = lm.get("env_vars", {})
        renv = rm.get("env_vars", {})
        env_changes: dict[str, Any] = {}
        for k in sorted(set(lenv) | set(renv)):
            lv, rv = lenv.get(k), renv.get(k)
            if lv != rv:
                env_changes[k] = {"from": lv, "to": rv}
        result["env_changed"] = env_changes

        # Runtime diff
        lr = lm.get("runtime")
        rr = rm.get("runtime")
        if lr != rr:
            result["runtime_changed"] = {"from": lr, "to": rr}

        # Git diff
        lgit = lm.get("git_sha")
        rgit = rm.get("git_sha")
        if lgit != rgit:
            result["git_changed"] = {"from": lgit, "to": rgit}
        if rm.get("git_diff"):
            result["code_diff"] = rm["git_diff"]

        return result

    # ---- Metrics comparison -------------------------------------------

    def compare_windows(
        self,
        metric_name: str,
        window1_start: str,
        window1_end: str,
        window2_start: str,
        window2_end: str,
    ) -> dict[str, Any]:
        """Compare a metric between two time windows."""

        def _window_stats(start: str, end: str) -> dict[str, Any]:
            rows = self._storage.execute_sql(
                "SELECT "
                "count(*) AS count, "
                "avg(json_extract(meta, '$.value')) AS avg, "
                "min(json_extract(meta, '$.value')) AS min, "
                "max(json_extract(meta, '$.value')) AS max "
                "FROM events WHERE event_type = 'metric' AND name = ? "
                "AND timestamp >= ? AND timestamp <= ?",
                (metric_name, start, end),
            )
            return rows[0] if rows else {}

        w1 = _window_stats(window1_start, window1_end)
        w2 = _window_stats(window2_start, window2_end)

        result: dict[str, Any] = {
            "metric": metric_name,
            "window1": {"start": window1_start, "end": window1_end, **w1},
            "window2": {"start": window2_start, "end": window2_end, **w2},
        }

        # Compute pct change on avg
        avg1 = w1.get("avg")
        avg2 = w2.get("avg")
        if avg1 and avg2 and avg1 != 0:
            result["avg_change_pct"] = round((avg2 - avg1) / avg1 * 100, 2)

        return result

    # ---- Correlation --------------------------------------------------

    def correlate(
        self,
        *,
        since: str | None = None,
        window: str = "2h",
    ) -> dict[str, Any]:
        """Find what changed around when errors spiked."""
        since_iso = _since_to_iso(since) or _since_to_iso("24h")

        # Find when error rate spiked
        error_times = self._storage.execute_sql(
            "SELECT timestamp FROM events WHERE event_type = 'error' "
            "AND timestamp >= ? ORDER BY timestamp ASC LIMIT 1",
            (since_iso,),
        )
        if not error_times:
            return {"message": "No errors found in the given window"}

        first_error_ts = error_times[0]["timestamp"]

        # Find snapshots near the error spike
        window_delta = _since_to_iso(window)
        snapshots = self._storage.execute_sql(
            "SELECT event_id AS snapshot_id, timestamp, meta "
            "FROM events WHERE event_type = 'snapshot' "
            "AND timestamp <= ? AND timestamp >= ? "
            "ORDER BY timestamp DESC",
            (first_error_ts, window_delta),
        )

        # Get error summary around that time
        errors = self._storage.execute_sql(
            "SELECT name, json_extract(meta, '$.fingerprint') AS fingerprint, "
            "json_extract(meta, '$.message') AS message, count(*) AS cnt "
            "FROM events WHERE event_type = 'error' AND timestamp >= ? "
            "GROUP BY fingerprint ORDER BY cnt DESC LIMIT 10",
            (since_iso,),
        )

        return {
            "first_error_at": first_error_ts,
            "nearby_snapshots": snapshots,
            "error_summary": errors,
        }

    # ---- Raw SQL ------------------------------------------------------

    def sql(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Raw SQL escape hatch."""
        return self._storage.execute_sql(query, params)

    def _add_duration_percentiles(
        self, result: dict[str, Any], where: str, params: list[Any]
    ) -> None:
        durations = self._storage.execute_sql(
            f"SELECT duration_ms FROM events WHERE {where} "
            f"AND duration_ms IS NOT NULL ORDER BY duration_ms ASC",
            tuple(params),
        )
        values = [row["duration_ms"] for row in durations if row.get("duration_ms") is not None]
        if not values:
            result["p50_duration_ms"] = None
            result["p95_duration_ms"] = None
            result["p99_duration_ms"] = None
            return

        result["p50_duration_ms"] = _percentile(values, 0.50)
        result["p95_duration_ms"] = _percentile(values, 0.95)
        result["p99_duration_ms"] = _percentile(values, 0.99)


def _parse_bucket(bucket: str) -> int:
    """Parse bucket string like '1h', '5m', '1d' into seconds."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    suffix = bucket[-1]
    if suffix in units:
        try:
            return int(bucket[:-1]) * units[suffix]
        except ValueError:
            pass
    return 3600  # default 1h


def _percentile(values: list[float], quantile: float) -> float | None:
    """Compute a simple interpolated percentile for sorted duration values."""
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)

    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    interpolated = values[lower] * (1 - weight) + values[upper] * weight
    return round(interpolated, 2)
