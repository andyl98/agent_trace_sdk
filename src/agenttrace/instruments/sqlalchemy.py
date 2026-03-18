"""SQLAlchemy event-based instrumentation."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AgentTrace

_OP_RE = re.compile(
    r"^\s*(SELECT|INSERT|UPDATE|DELETE)\b.*?\b(FROM|INTO)\s+[\"']?(\w+)",
    re.IGNORECASE | re.DOTALL,
)


def _extract_operation(statement: str) -> str:
    """Extract operation + table name from SQL, e.g. 'SELECT orders'."""
    m = _OP_RE.match(statement)
    if m:
        return f"{m.group(1).upper()} {m.group(3)}"
    # Fallback: first 50 chars
    return statement[:50].strip()


def instrument_sqlalchemy(client: AgentTrace, engine: Any) -> None:
    """Attach event listeners to a SQLAlchemy engine for query span capture."""
    from sqlalchemy import event

    @event.listens_for(engine, "before_cursor_execute")
    def _before_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        info = conn.info
        info["agenttrace_start"] = time.perf_counter()
        info["agenttrace_statement"] = statement
        span_id = client._start_span(
            name=_extract_operation(statement),
            kind="db",
            meta={"query": statement[:2000]},
        )
        info["agenttrace_span_id"] = span_id

    @event.listens_for(engine, "after_cursor_execute")
    def _after_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        info = conn.info
        start = info.pop("agenttrace_start", None)
        span_id = info.pop("agenttrace_span_id", None)
        info.pop("agenttrace_statement", None)
        if start is None or span_id is None:
            return

        duration_ms = (time.perf_counter() - start) * 1000
        meta_updates: dict[str, Any] = {"rowcount": cursor.rowcount}

        # Capture EXPLAIN QUERY PLAN for slow queries (SQLite only)
        if duration_ms > client._config.slow_query_threshold_ms:
            try:
                raw_conn = conn.connection.connection  # unwrap to raw dbapi conn
                plan_cursor = raw_conn.execute(f"EXPLAIN QUERY PLAN {statement}")
                meta_updates["query_plan"] = [
                    dict(zip(["id", "parent", "notused", "detail"], row))
                    for row in plan_cursor.fetchall()
                ]
            except Exception:
                pass  # not all statements/backends support EXPLAIN

        client._end_span(span_id, "ok", duration_ms, meta_updates)

    @event.listens_for(engine, "handle_error")
    def _on_error(exception_context: Any) -> None:
        info = exception_context.connection.info
        span_id = info.pop("agenttrace_span_id", None)
        start = info.pop("agenttrace_start", None)
        info.pop("agenttrace_statement", None)
        if span_id and start:
            duration_ms = (time.perf_counter() - start) * 1000
            client._end_span(
                span_id,
                "error",
                duration_ms,
                {"error_msg": str(exception_context.original_exception)},
            )
            client.capture_error(exception_context.original_exception)
