"""AgentTrace: Observability SDK for AI-operated applications."""

from .client import AgentTrace
from .types import AgentTraceConfig, Event, SpanView, TraceView

__version__ = "0.1.0"
__all__ = ["AgentTrace", "Event", "AgentTraceConfig", "TraceView", "SpanView"]
