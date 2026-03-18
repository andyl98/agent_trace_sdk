"""Trace/span context propagation via contextvars."""

from __future__ import annotations

import contextvars
from contextlib import contextmanager

_current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agenttrace_trace_id", default=None
)
_current_span_stack: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
    "agenttrace_span_stack", default=[]
)


def get_trace_id() -> str | None:
    return _current_trace_id.get()


def set_trace_id(trace_id: str) -> contextvars.Token[str | None]:
    return _current_trace_id.set(trace_id)


def get_current_span_id() -> str | None:
    stack = _current_span_stack.get()
    return stack[-1] if stack else None


def push_span(span_id: str) -> None:
    stack = _current_span_stack.get()
    _current_span_stack.set([*stack, span_id])  # copy-on-write


def pop_span() -> str | None:
    stack = _current_span_stack.get()
    if not stack:
        return None
    _current_span_stack.set(stack[:-1])
    return stack[-1]


@contextmanager
def trace_context(trace_id: str):
    """Scoped context manager that sets trace_id for the duration."""
    trace_token = _current_trace_id.set(trace_id)
    span_token = _current_span_stack.set([])
    try:
        yield
    finally:
        _current_trace_id.reset(trace_token)
        _current_span_stack.reset(span_token)
