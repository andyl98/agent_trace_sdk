"""HTTPX client instrumentation via event hooks."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from .. import context

if TYPE_CHECKING:
    from ..client import AgentTrace


def instrument_httpx(client: AgentTrace, httpx_client: Any) -> None:
    """Add event hooks to an httpx.Client or httpx.AsyncClient for outbound HTTP span capture."""
    import httpx

    def on_request(request: httpx.Request) -> None:
        span_id = client._start_span(
            name=f"{request.method} {request.url.host}{request.url.path}",
            kind="http_client",
            meta={
                "http.method": str(request.method),
                "http.url": str(request.url),
                "http.host": str(request.url.host),
            },
        )
        # Propagate trace context
        trace_id = context.get_trace_id()
        if trace_id:
            request.headers["X-Trace-Id"] = trace_id
        # Stash for response hook
        request.extensions["agenttrace_span_id"] = span_id
        request.extensions["agenttrace_start"] = time.perf_counter()

    def on_response(response: httpx.Response) -> None:
        span_id = response.request.extensions.get("agenttrace_span_id")
        start = response.request.extensions.get("agenttrace_start")
        if not span_id or not start:
            return
        duration_ms = (time.perf_counter() - start) * 1000
        status = "error" if response.status_code >= 400 else "ok"
        meta_updates: dict[str, Any] = {
            "http.status_code": response.status_code,
        }
        client._end_span(span_id, status, duration_ms, meta_updates)
        client.metric(
            "http.client.duration",
            duration_ms,
            tags={
                "method": str(response.request.method),
                "host": str(response.request.url.host),
                "status": response.status_code,
            },
        )

    async def on_request_async(request: httpx.Request) -> None:
        on_request(request)

    async def on_response_async(response: httpx.Response) -> None:
        on_response(response)

    if isinstance(httpx_client, httpx.AsyncClient):
        httpx_client.event_hooks.setdefault("request", []).append(on_request_async)
        httpx_client.event_hooks.setdefault("response", []).append(on_response_async)
    else:
        httpx_client.event_hooks.setdefault("request", []).append(on_request)
        httpx_client.event_hooks.setdefault("response", []).append(on_response)
