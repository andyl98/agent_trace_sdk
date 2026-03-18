"""Raw ASGI middleware for HTTP trace instrumentation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from .. import context
from ..types import Event

if TYPE_CHECKING:
    from ..client import AgentTrace


def create_middleware(client: AgentTrace) -> type:
    """Returns an ASGI middleware class bound to the given AgentTrace client."""

    class AgentTraceMiddleware:
        def __init__(self, app: Any) -> None:
            self.app = app

        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            method = scope.get("method", "UNKNOWN")
            path = scope.get("path", "/")
            # Strip trailing slash for consistency
            if path != "/" and path.endswith("/"):
                path = path.rstrip("/")

            # Extract headers
            raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
            headers = {
                k.decode("latin-1"): v.decode("latin-1") for k, v in raw_headers
            }

            # Check for propagated trace id
            incoming_trace_id = headers.get("x-trace-id")

            # Build request meta (nested so json_extract works: $.http.path)
            meta: dict[str, Any] = {
                "http": {
                    "method": method,
                    "path": path,
                    "query": scope.get("query_string", b"").decode("latin-1"),
                    "user_agent": headers.get("user-agent", ""),
                    "content_type": headers.get("content-type", ""),
                    "headers": client._redact_headers(headers),
                }
            }

            # Start trace
            trace_name = f"{method} {path}"
            trace_id = client._start_trace(trace_name, kind="http", meta=meta)
            start_time = time.perf_counter()

            # If there was an incoming trace id, note it
            if incoming_trace_id:
                client._storage.update_event(trace_id, meta={"parent_trace_id": incoming_trace_id})

            # Track response status
            response_status: list[int] = [200]  # default

            async def send_wrapper(message: dict) -> None:
                if message["type"] == "http.response.start":
                    response_status[0] = message.get("status", 200)
                    # Inject X-Trace-Id header
                    resp_headers = list(message.get("headers", []))
                    resp_headers.append(
                        (b"x-trace-id", trace_id.encode("latin-1"))
                    )
                    message = {**message, "headers": resp_headers}
                await send(message)

            # Execute the app within trace context
            error_occurred = False
            with context.trace_context(trace_id):
                try:
                    await self.app(scope, receive, send_wrapper)
                except Exception as exc:
                    error_occurred = True
                    client.capture_error(exc)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    status_code = response_status[0]
                    status = "error" if error_occurred or status_code >= 400 else "ok"
                    client._end_trace(
                        trace_id,
                        status=status,
                        duration_ms=duration_ms,
                        meta_updates={
                            "http": {
                                "status_code": status_code,
                                "duration_ms": duration_ms,
                            }
                        },
                    )
                    if not error_occurred and status_code >= 400:
                        level = "warning" if 400 <= status_code < 500 else "error"
                        event = Event.error(
                            error_type="HTTPStatusError",
                            message=f"HTTP {status_code} for {method} {path}",
                            trace_id=trace_id,
                            status_code=status_code,
                            level=level,
                            meta={
                                "http": {
                                    "method": method,
                                    "path": path,
                                }
                            },
                            service_name=client._config.service_name,
                        )
                        client._storage.write_event(event)
                    # Record duration metric
                    client.metric(
                        "http.request.duration",
                        duration_ms,
                        tags={"method": method, "path": path, "status": status_code},
                    )

    return AgentTraceMiddleware
