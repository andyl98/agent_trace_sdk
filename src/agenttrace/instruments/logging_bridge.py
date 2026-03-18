"""Bridge Python stdlib logging to agenttrace events."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .. import context
from .._utils import new_id, utc_now_iso
from ..types import Event

if TYPE_CHECKING:
    from ..client import AgentTrace


class AgentTraceLogHandler(logging.Handler):
    """Logging handler that writes WARNING+ records as agenttrace events."""

    def __init__(self, client: AgentTrace, min_level: int = logging.WARNING) -> None:
        super().__init__(level=min_level)
        self._client = client

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._emit_impl(record)
        except Exception:
            self.handleError(record)

    def _emit_impl(self, record: logging.LogRecord) -> None:
        trace_id = context.get_trace_id()
        span_id = context.get_current_span_id()

        meta = {
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
            "pathname": record.pathname,
            "lineno": record.lineno,
            "func_name": record.funcName,
        }

        # If there's an exception, capture as error event
        if record.exc_info and record.exc_info[1]:
            self._client.capture_error(
                record.exc_info[1],
                level=record.levelname.lower(),
                meta=meta,
            )
            return

        event = Event(
            event_id=new_id(),
            event_type="log",
            timestamp=utc_now_iso(),
            trace_id=trace_id,
            span_id=span_id,
            name=record.name,
            kind="log",
            status=record.levelname.lower(),
            meta=meta,
            service_name=self._client._config.service_name,
        )
        self._client._storage.write_event(event)


def install_log_bridge(
    client: AgentTrace, min_level: int = logging.WARNING
) -> AgentTraceLogHandler:
    """Install the agenttrace handler on the root logger."""
    handler = AgentTraceLogHandler(client, min_level)
    logging.getLogger().addHandler(handler)
    return handler
