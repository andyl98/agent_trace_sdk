"""Canonical event envelope and configuration types."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from ._utils import new_id, utc_now_iso


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

_VOLATILE_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # UUID
    r"|0x[0-9a-fA-F]+"  # hex
    r"|\b\d+\b",  # integers
    re.IGNORECASE,
)


def compute_fingerprint(error_type: str | None, message: str) -> str:
    """Stable fingerprint: strip volatile tokens, hash with error type."""
    normalized = _VOLATILE_RE.sub("<X>", message)
    raw = f"{error_type or 'Unknown'}:{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Canonical Event Envelope
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Event:
    """Every piece of telemetry is an Event row."""

    event_id: str
    event_type: str  # trace | span | error | metric | snapshot | log
    timestamp: str  # ISO 8601 UTC
    name: str
    trace_id: str | None = None
    span_id: str | None = None
    parent_id: str | None = None
    kind: str | None = None
    status: str | None = None
    duration_ms: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    service_name: str | None = None
    snapshot_id: str | None = None

    # -- Factory helpers --------------------------------------------------

    @classmethod
    def trace(
        cls,
        name: str,
        kind: str = "http",
        *,
        meta: dict[str, Any] | None = None,
        service_name: str | None = None,
        snapshot_id: str | None = None,
    ) -> Event:
        trace_id = new_id()
        return cls(
            event_id=trace_id,
            event_type="trace",
            timestamp=utc_now_iso(),
            trace_id=trace_id,
            name=name,
            kind=kind,
            meta=meta or {},
            service_name=service_name,
            snapshot_id=snapshot_id,
        )

    @classmethod
    def span(
        cls,
        trace_id: str,
        name: str,
        kind: str = "custom",
        *,
        parent_id: str | None = None,
        meta: dict[str, Any] | None = None,
        service_name: str | None = None,
    ) -> Event:
        span_id = new_id()
        return cls(
            event_id=span_id,
            event_type="span",
            timestamp=utc_now_iso(),
            trace_id=trace_id,
            span_id=span_id,
            parent_id=parent_id,
            name=name,
            kind=kind,
            meta=meta or {},
            service_name=service_name,
        )

    @classmethod
    def error(
        cls,
        error_type: str,
        message: str,
        *,
        trace_id: str | None = None,
        span_id: str | None = None,
        stack_trace: str | None = None,
        status_code: int | None = None,
        level: str = "error",
        meta: dict[str, Any] | None = None,
        service_name: str | None = None,
    ) -> Event:
        m = dict(meta or {})
        m.update(
            {
                "message": message,
                "error_type": error_type,
                "fingerprint": compute_fingerprint(error_type, message),
            }
        )
        if stack_trace:
            m["stack_trace"] = stack_trace
        if status_code is not None:
            m["status_code"] = status_code
        return cls(
            event_id=new_id(),
            event_type="error",
            timestamp=utc_now_iso(),
            trace_id=trace_id,
            span_id=span_id,
            name=error_type,
            kind="error",
            status=level,
            meta=m,
            service_name=service_name,
        )

    @classmethod
    def metric(
        cls,
        name: str,
        value: float,
        *,
        tags: dict[str, Any] | None = None,
        service_name: str | None = None,
        snapshot_id: str | None = None,
    ) -> Event:
        return cls(
            event_id=new_id(),
            event_type="metric",
            timestamp=utc_now_iso(),
            name=name,
            kind="metric",
            meta={"value": value, "tags": tags or {}},
            service_name=service_name,
            snapshot_id=snapshot_id,
        )

    @classmethod
    def snapshot(
        cls,
        *,
        git_sha: str | None = None,
        git_diff: str | None = None,
        dependencies: dict[str, str] | None = None,
        runtime: str | None = None,
        env_vars: dict[str, str] | None = None,
        service_name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Event:
        m: dict[str, Any] = {}
        if git_sha is not None:
            m["git_sha"] = git_sha
        if git_diff is not None:
            m["git_diff"] = git_diff
        if dependencies is not None:
            m["dependencies"] = dependencies
        if runtime is not None:
            m["runtime"] = runtime
        if env_vars is not None:
            m["env_vars"] = env_vars
        if extra:
            m.update(extra)
        eid = new_id()
        return cls(
            event_id=eid,
            event_type="snapshot",
            timestamp=utc_now_iso(),
            name="deploy_snapshot",
            kind="snapshot",
            meta=m,
            service_name=service_name,
            snapshot_id=eid,
        )


# ---------------------------------------------------------------------------
# Read-side projections (for query results)
# ---------------------------------------------------------------------------


@dataclass
class SpanView:
    span_id: str
    trace_id: str
    parent_id: str | None
    name: str
    kind: str
    started_at: str
    ended_at: str | None
    duration_ms: float | None
    meta: dict[str, Any]
    error: bool
    error_msg: str | None = None


@dataclass
class TraceView:
    trace_id: str
    name: str
    kind: str
    status_code: int | None
    error: bool
    started_at: str
    ended_at: str | None
    duration_ms: float | None
    meta: dict[str, Any]
    spans: list[SpanView] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class AgentTraceConfig:
    db_path: str = ".agenttrace.db"
    service_name: str = "default"
    auto_instrument: dict[str, bool] = field(
        default_factory=lambda: {
            "http": True,
            "db": True,
            "httpx": True,
            "logging": True,
        }
    )
    retention_days: int = 7
    slow_query_threshold_ms: float = 100.0
    redact_headers: list[str] = field(
        default_factory=lambda: [
            "authorization",
            "cookie",
            "set-cookie",
            "x-api-key",
        ]
    )
    env_safelist: list[str] = field(default_factory=list)
    max_meta_size_bytes: int = 65536
