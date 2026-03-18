"""Main AgentTrace client — the primary public API."""

from __future__ import annotations

import asyncio
import functools
import os
import subprocess
import sys
import time
import traceback
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .query import QueryAPI

from . import context
from ._utils import new_id, redact_dict, utc_now_iso
from .storage import Storage
from .types import AgentTraceConfig, Event


class SpanHandle:
    """Dual sync/async context manager + decorator for spans."""

    def __init__(
        self,
        client: AgentTrace,
        name: str,
        kind: str,
        meta: dict[str, Any] | None,
    ) -> None:
        self._client = client
        self._name = name
        self._kind = kind
        self._meta = meta or {}
        self._span_id: str | None = None
        self._start_time: float = 0.0

    # -- sync context manager -------------------------------------------

    def __enter__(self) -> SpanHandle:
        self._start_time = time.perf_counter()
        self._span_id = self._client._start_span(self._name, self._kind, self._meta)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:  # type: ignore[type-arg]
        duration = (time.perf_counter() - self._start_time) * 1000
        status = "error" if exc_type else "ok"
        meta_updates: dict[str, Any] = {}
        if exc_val:
            meta_updates["error_msg"] = str(exc_val)
            self._client.capture_error(exc_val)
        self._client._end_span(self._span_id, status, duration, meta_updates)
        return False  # don't suppress exceptions

    # -- async context manager ------------------------------------------

    async def __aenter__(self) -> SpanHandle:
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:  # type: ignore[type-arg]
        return self.__exit__(exc_type, exc_val, exc_tb)

    # -- decorator -------------------------------------------------------

    def __call__(self, fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                async with self.__class__(
                    self._client, self._name, self._kind, self._meta
                ):
                    return await fn(*args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.__class__(
                    self._client, self._name, self._kind, self._meta
                ):
                    return fn(*args, **kwargs)

            return sync_wrapper

    def annotate(self, **kwargs: Any) -> None:
        if self._span_id:
            self._client._storage.update_event(self._span_id, meta=kwargs)


class AgentTrace:
    """Observability SDK for AI-operated applications."""

    def __init__(
        self,
        db_path: str = ".agenttrace.db",
        service_name: str = "default",
        auto_instrument: dict[str, bool] | None = None,
        retention_days: int = 7,
        slow_query_threshold_ms: float = 100.0,
        redact_headers: list[str] | None = None,
        env_safelist: list[str] | None = None,
    ) -> None:
        self._config = AgentTraceConfig(
            db_path=db_path,
            service_name=service_name,
            auto_instrument=auto_instrument
            or {"http": True, "db": True, "httpx": True, "logging": True},
            retention_days=retention_days,
            slow_query_threshold_ms=slow_query_threshold_ms,
            redact_headers=redact_headers
            or ["authorization", "cookie", "set-cookie", "x-api-key"],
            env_safelist=env_safelist or [],
        )
        self._storage = Storage(db_path)
        self._storage.initialize()
        self._storage.purge_old(retention_days)
        self._current_snapshot_id: str | None = None

        # Auto-install logging bridge
        if self._config.auto_instrument.get("logging"):
            try:
                from .instruments.logging_bridge import install_log_bridge

                install_log_bridge(self)
            except Exception:
                pass  # don't break app if logging bridge fails

    # ---- Query API ----------------------------------------------------

    def query(self) -> "QueryAPI":
        """Return a QueryAPI instance bound to this client's storage."""
        from .query import QueryAPI

        return QueryAPI(self._storage)

    # ---- Middleware factory -------------------------------------------

    def middleware(self):
        """Returns a Starlette/FastAPI ASGI middleware class."""
        from .instruments.fastapi_middleware import create_middleware

        return create_middleware(self)

    # ---- Span ---------------------------------------------------------

    def span(
        self,
        name: str,
        kind: str = "custom",
        meta: dict[str, Any] | None = None,
    ) -> SpanHandle:
        """Create a span. Use as context manager, async context manager, or decorator."""
        return SpanHandle(self, name, kind, meta)

    def intent(
        self,
        intent: str,
        *,
        inputs: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> SpanHandle:
        """Create a semantic intent span for an agent-visible unit of work."""
        semantic_meta: dict[str, Any] = {
            "semantic": {
                "type": "intent",
                "intent": intent,
            }
        }
        if inputs is not None:
            semantic_meta["semantic"]["inputs"] = inputs
        if expected is not None:
            semantic_meta["semantic"]["expected"] = expected
        if meta:
            semantic_meta.update(meta)
        return SpanHandle(self, intent, "intent", semantic_meta)

    def observe_intent(
        self,
        intent: str,
        *,
        inputs: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> SpanHandle:
        """Alias for intent() to support a more explicit call site."""
        return self.intent(intent, inputs=inputs, expected=expected, meta=meta)

    def record_decision(
        self,
        name: str,
        *,
        chosen: Any | None = None,
        reason: str | None = None,
        alternatives: list[Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Record a decision point as a zero-duration semantic span."""
        semantic_meta: dict[str, Any] = {
            "semantic": {
                "type": "decision",
                "decision": name,
            }
        }
        if chosen is not None:
            semantic_meta["semantic"]["chosen"] = chosen
        if reason is not None:
            semantic_meta["semantic"]["reason"] = reason
        if alternatives is not None:
            semantic_meta["semantic"]["alternatives"] = alternatives
        if meta:
            semantic_meta.update(meta)
        return self._record_semantic_event(name, "decision", semantic_meta)

    def record_invariant(
        self,
        name: str,
        passed: bool,
        *,
        expected: Any | None = None,
        actual: Any | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Record whether an invariant held at runtime."""
        semantic_meta: dict[str, Any] = {
            "semantic": {
                "type": "invariant",
                "name": name,
                "passed": passed,
            }
        }
        if expected is not None:
            semantic_meta["semantic"]["expected"] = expected
        if actual is not None:
            semantic_meta["semantic"]["actual"] = actual
        if meta:
            semantic_meta.update(meta)
        status = "ok" if passed else "error"
        return self._record_semantic_event(name, "invariant", semantic_meta, status=status)

    def record_fallback(
        self,
        name: str,
        *,
        reason: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Record a graceful-degradation or fallback path."""
        semantic_meta: dict[str, Any] = {
            "semantic": {
                "type": "fallback",
                "name": name,
            }
        }
        if reason is not None:
            semantic_meta["semantic"]["reason"] = reason
        if meta:
            semantic_meta.update(meta)
        return self._record_semantic_event(name, "fallback", semantic_meta)

    # ---- Error capture ------------------------------------------------

    def capture_error(
        self,
        error: BaseException,
        *,
        level: str = "error",
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Record a structured error event. Returns event_id."""
        error_type = type(error).__name__
        message = str(error)
        stack = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        event = Event.error(
            error_type=error_type,
            message=message,
            trace_id=context.get_trace_id(),
            span_id=context.get_current_span_id(),
            stack_trace=stack,
            level=level,
            meta=meta,
            service_name=self._config.service_name,
        )
        self._storage.write_event(event)
        return event.event_id

    # ---- Metrics ------------------------------------------------------

    def metric(
        self, name: str, value: float, tags: dict[str, Any] | None = None
    ) -> str:
        """Record a metric data point. Returns event_id."""
        event = Event.metric(
            name=name,
            value=value,
            tags=tags,
            service_name=self._config.service_name,
            snapshot_id=self._current_snapshot_id,
        )
        self._storage.write_event(event)
        return event.event_id

    # ---- Annotations --------------------------------------------------

    def annotate(self, **kwargs: Any) -> None:
        """Add key-value metadata to the current span."""
        span_id = context.get_current_span_id()
        if span_id:
            self._storage.update_event(span_id, meta=kwargs)

    # ---- Startup / Snapshot -------------------------------------------

    def record_startup(
        self,
        *,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Capture a deployment snapshot and record a service-restart intent.

        Call this in your application's startup handler so that every
        (re)start is automatically visible to agents — they can correlate
        deploys, dependency changes, and config shifts with runtime
        behaviour changes.

        Returns the snapshot event_id.
        """
        snapshot_id = self.snapshot()

        startup_inputs: dict[str, Any] = {
            "service": self._config.service_name,
            "snapshot_id": self._current_snapshot_id or "",
        }
        if meta:
            startup_inputs.update(meta)

        with context.trace_context(new_id()):
            self._record_semantic_event(
                "service-restart",
                "intent",
                {
                    "semantic": {
                        "type": "intent",
                        "intent": "service-restart",
                        "inputs": startup_inputs,
                        "expected": {"result": "service_ready"},
                    }
                },
            )

        return snapshot_id

    def snapshot(self) -> str:
        """Capture deployment snapshot. Returns snapshot_id."""
        git_sha = self._run_cmd("git", "rev-parse", "HEAD")
        git_diff = self._run_cmd("git", "diff", "HEAD")

        deps = self._capture_dependencies()
        runtime = f"python {sys.version}"
        env_vars = {
            k: os.environ.get(k, "")
            for k in self._config.env_safelist
            if k in os.environ
        }

        event = Event.snapshot(
            git_sha=git_sha,
            git_diff=git_diff,
            dependencies=deps,
            runtime=runtime,
            env_vars=env_vars,
            service_name=self._config.service_name,
        )
        self._storage.write_event(event)
        self._current_snapshot_id = event.snapshot_id
        return event.event_id

    # ---- Instrument helpers -------------------------------------------

    def instrument_engine(self, engine: Any) -> None:
        """Instrument a SQLAlchemy engine."""
        from .instruments.sqlalchemy import instrument_sqlalchemy

        instrument_sqlalchemy(self, engine)

    def instrument_httpx(self, httpx_client: Any) -> None:
        """Instrument an httpx client."""
        from .instruments.httpx_client import instrument_httpx

        instrument_httpx(self, httpx_client)

    # ---- Shutdown -----------------------------------------------------

    def shutdown(self) -> None:
        self._storage.close()

    # ---- Internal helpers ---------------------------------------------

    def _start_trace(
        self, name: str, kind: str, meta: dict[str, Any] | None = None
    ) -> str:
        event = Event.trace(
            name=name,
            kind=kind,
            meta=meta,
            service_name=self._config.service_name,
            snapshot_id=self._current_snapshot_id,
        )
        self._storage.write_event(event)
        return event.trace_id  # type: ignore[return-value]

    def _end_trace(
        self,
        trace_id: str,
        status: str,
        duration_ms: float,
        meta_updates: dict[str, Any] | None = None,
    ) -> None:
        fields: dict[str, Any] = {"status": status, "duration_ms": duration_ms}
        if meta_updates:
            fields["meta"] = meta_updates
        self._storage.update_event(trace_id, **fields)

    def _start_span(
        self, name: str, kind: str, meta: dict[str, Any] | None = None
    ) -> str:
        trace_id = context.get_trace_id()
        parent_id = context.get_current_span_id()
        event = Event.span(
            trace_id=trace_id or "",
            name=name,
            kind=kind,
            parent_id=parent_id,
            meta=meta,
            service_name=self._config.service_name,
        )
        self._storage.write_event(event)
        context.push_span(event.span_id)  # type: ignore[arg-type]
        return event.span_id  # type: ignore[return-value]

    def _end_span(
        self,
        span_id: str | None,
        status: str,
        duration_ms: float,
        meta_updates: dict[str, Any] | None = None,
    ) -> None:
        if not span_id:
            return
        context.pop_span()
        fields: dict[str, Any] = {"status": status, "duration_ms": duration_ms}
        if meta_updates:
            fields["meta"] = meta_updates
        self._storage.update_event(span_id, **fields)

    def _redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
        return redact_dict(headers, self._config.redact_headers)

    def _record_semantic_event(
        self,
        name: str,
        kind: str,
        meta: dict[str, Any],
        *,
        status: str = "ok",
    ) -> str:
        trace_id = context.get_trace_id()
        parent_id = context.get_current_span_id()
        event = Event.span(
            trace_id=trace_id or "",
            name=name,
            kind=kind,
            parent_id=parent_id,
            meta=meta,
            service_name=self._config.service_name,
        )
        event.status = status
        event.duration_ms = 0.0
        self._storage.write_event(event)
        return event.event_id

    @staticmethod
    def _run_cmd(*args: str) -> str | None:
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

    @staticmethod
    def _capture_dependencies() -> dict[str, str]:
        """Capture installed Python packages."""
        try:
            import importlib.metadata

            return {
                d.metadata["Name"]: d.version
                for d in importlib.metadata.distributions()
            }
        except Exception:
            return {}
