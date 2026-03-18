"""Tests for core SDK functionality: types, storage, context, client."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from agenttrace import AgentTrace, Event
from agenttrace.context import (
    get_current_span_id,
    get_trace_id,
    pop_span,
    push_span,
    set_trace_id,
    trace_context,
)
from agenttrace.storage import Storage
from agenttrace.types import compute_fingerprint


# ---------------------------------------------------------------------------
# types.py
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_strips_uuids(self):
        fp1 = compute_fingerprint("ValueError", "User abc12345-1234-1234-1234-123456789abc not found")
        fp2 = compute_fingerprint("ValueError", "User 99999999-9999-9999-9999-999999999999 not found")
        assert fp1 == fp2

    def test_strips_integers(self):
        fp1 = compute_fingerprint("TimeoutError", "Request 12345 timed out after 30s")
        fp2 = compute_fingerprint("TimeoutError", "Request 99999 timed out after 30s")
        assert fp1 == fp2

    def test_different_types_differ(self):
        fp1 = compute_fingerprint("ValueError", "not found")
        fp2 = compute_fingerprint("KeyError", "not found")
        assert fp1 != fp2


class TestEventFactories:
    def test_trace(self):
        e = Event.trace("GET /api/foo", kind="http", meta={"path": "/api/foo"})
        assert e.event_type == "trace"
        assert e.trace_id == e.event_id
        assert e.name == "GET /api/foo"
        assert e.meta["path"] == "/api/foo"

    def test_span(self):
        e = Event.span("trace1", "db.query", kind="db", parent_id="span0")
        assert e.event_type == "span"
        assert e.trace_id == "trace1"
        assert e.parent_id == "span0"

    def test_error(self):
        e = Event.error("ValueError", "bad input", status_code=422)
        assert e.event_type == "error"
        assert e.meta["fingerprint"]
        assert e.meta["status_code"] == 422

    def test_metric(self):
        e = Event.metric("http.duration", 42.5, tags={"path": "/api"})
        assert e.meta["value"] == 42.5
        assert e.meta["tags"]["path"] == "/api"

    def test_snapshot(self):
        e = Event.snapshot(git_sha="abc123", dependencies={"fastapi": "0.100.0"})
        assert e.event_type == "snapshot"
        assert e.meta["git_sha"] == "abc123"
        assert e.snapshot_id == e.event_id


# ---------------------------------------------------------------------------
# context.py
# ---------------------------------------------------------------------------


class TestContext:
    def test_trace_id(self):
        assert get_trace_id() is None
        token = set_trace_id("t1")
        assert get_trace_id() == "t1"
        from contextvars import copy_context
        # reset
        from agenttrace.context import _current_trace_id
        _current_trace_id.reset(token)

    def test_span_stack(self):
        assert get_current_span_id() is None
        push_span("s1")
        assert get_current_span_id() == "s1"
        push_span("s2")
        assert get_current_span_id() == "s2"
        pop_span()
        assert get_current_span_id() == "s1"
        pop_span()
        assert get_current_span_id() is None

    def test_trace_context_manager(self):
        with trace_context("t2"):
            assert get_trace_id() == "t2"
            push_span("s3")
            assert get_current_span_id() == "s3"
        assert get_trace_id() is None
        assert get_current_span_id() is None


# ---------------------------------------------------------------------------
# storage.py
# ---------------------------------------------------------------------------


class TestStorage:
    def setup_method(self):
        self.tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmpfile.close()
        self.storage = Storage(self.tmpfile.name)
        self.storage.initialize()

    def teardown_method(self):
        self.storage.close()
        os.unlink(self.tmpfile.name)

    def test_write_and_query(self):
        e = Event.trace("GET /test", kind="http")
        self.storage.write_event(e)

        rows = self.storage.query_events(event_type="trace")
        assert len(rows) == 1
        assert rows[0]["name"] == "GET /test"

    def test_update_event(self):
        e = Event.trace("GET /test", kind="http")
        self.storage.write_event(e)

        self.storage.update_event(e.event_id, status="ok", duration_ms=42.0)
        rows = self.storage.query_events(trace_id=e.trace_id)
        assert rows[0]["status"] == "ok"
        assert rows[0]["duration_ms"] == 42.0

    def test_meta_merge(self):
        e = Event.trace("GET /test", kind="http", meta={"a": 1})
        self.storage.write_event(e)

        self.storage.update_event(e.event_id, meta={"b": 2})
        rows = self.storage.query_events(trace_id=e.trace_id)
        assert rows[0]["meta"]["a"] == 1
        assert rows[0]["meta"]["b"] == 2

    def test_execute_sql(self):
        e = Event.trace("GET /test", kind="http")
        self.storage.write_event(e)

        rows = self.storage.execute_sql(
            "SELECT count(*) as cnt FROM events WHERE event_type = ?", ("trace",)
        )
        assert rows[0]["cnt"] == 1

    def test_purge_old(self):
        e = Event.trace("GET /old", kind="http")
        self.storage.write_event(e)
        # Manually backdate
        self.storage.conn.execute(
            "UPDATE events SET timestamp = datetime('now', '-30 days') WHERE event_id = ?",
            (e.event_id,),
        )
        self.storage.conn.commit()
        deleted = self.storage.purge_old(7)
        assert deleted == 1


# ---------------------------------------------------------------------------
# client.py
# ---------------------------------------------------------------------------


class TestClient:
    def setup_method(self):
        self.tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmpfile.close()
        self.client = AgentTrace(
            db_path=self.tmpfile.name, service_name="test-svc"
        )

    def teardown_method(self):
        self.client.shutdown()
        os.unlink(self.tmpfile.name)

    def test_span_sync(self):
        with trace_context("t1"):
            with self.client.span("compute", kind="compute") as s:
                x = 1 + 1
        # Should have a span in the DB
        rows = self.client._storage.query_events(event_type="span")
        assert len(rows) == 1
        assert rows[0]["name"] == "compute"
        assert rows[0]["duration_ms"] is not None
        assert rows[0]["status"] == "ok"

    def test_span_captures_error(self):
        with trace_context("t2"):
            try:
                with self.client.span("failing"):
                    raise ValueError("boom")
            except ValueError:
                pass

        spans = self.client._storage.query_events(event_type="span")
        assert spans[0]["status"] == "error"

        errors = self.client._storage.query_events(event_type="error")
        assert len(errors) == 1
        assert errors[0]["meta"]["message"] == "boom"

    def test_span_as_decorator(self):
        @self.client.span("decorated", kind="compute")
        def my_func(x):
            return x * 2

        with trace_context("t3"):
            result = my_func(5)
        assert result == 10

        spans = self.client._storage.query_events(event_type="span")
        assert len(spans) == 1
        assert spans[0]["name"] == "decorated"

    def test_capture_error(self):
        with trace_context("t4"):
            try:
                raise RuntimeError("test error")
            except RuntimeError as exc:
                eid = self.client.capture_error(exc)

        errors = self.client._storage.query_events(event_type="error")
        assert len(errors) == 1
        assert errors[0]["meta"]["error_type"] == "RuntimeError"
        assert errors[0]["meta"]["fingerprint"]

    def test_metric(self):
        self.client.metric("test.gauge", 99.9, tags={"env": "test"})
        rows = self.client._storage.query_events(event_type="metric")
        assert len(rows) == 1
        assert rows[0]["meta"]["value"] == 99.9

    def test_intent_span_records_semantic_context(self):
        with trace_context("t5"):
            with self.client.observe_intent(
                "Process checkout",
                inputs={"user_id": "u_123", "cart_total": 5000},
                expected={"result": "charge_created"},
            ):
                pass

        spans = self.client._storage.query_events(event_type="span", kind="intent")
        assert len(spans) == 1
        assert spans[0]["name"] == "Process checkout"
        assert spans[0]["meta"]["semantic"]["type"] == "intent"
        assert spans[0]["meta"]["semantic"]["inputs"]["cart_total"] == 5000
        assert spans[0]["meta"]["semantic"]["expected"]["result"] == "charge_created"

    def test_semantic_events_attach_to_current_span(self):
        with trace_context("t6"):
            with self.client.span("checkout-request", kind="compute"):
                decision_id = self.client.record_decision(
                    "Select carrier",
                    chosen="fedex",
                    reason="lowest_cost",
                    alternatives=["ups", "dhl"],
                )
                invariant_id = self.client.record_invariant(
                    "carrier_name present",
                    False,
                    expected="non-null string",
                    actual=None,
                )
                fallback_id = self.client.record_fallback(
                    "Use cached quote",
                    reason="upstream timeout",
                )

        spans = self.client._storage.query_events(event_type="span")
        span_map = {row["event_id"]: row for row in spans}
        decision = span_map[decision_id]
        invariant = span_map[invariant_id]
        fallback = span_map[fallback_id]
        parent_span = next(row for row in spans if row["name"] == "checkout-request")

        assert decision["parent_id"] == parent_span["span_id"]
        assert decision["kind"] == "decision"
        assert decision["meta"]["semantic"]["chosen"] == "fedex"
        assert decision["duration_ms"] == 0.0

        assert invariant["kind"] == "invariant"
        assert invariant["status"] == "error"
        assert invariant["meta"]["semantic"]["passed"] is False
        assert invariant["meta"]["semantic"]["expected"] == "non-null string"

        assert fallback["kind"] == "fallback"
        assert fallback["meta"]["semantic"]["reason"] == "upstream timeout"

    def test_record_startup_creates_snapshot_and_restart_intent(self):
        event_id = self.client.record_startup(
            meta={"db_path": "/tmp/test.db", "upstream_url": "http://localhost:8001"},
        )

        snapshots = self.client._storage.query_events(event_type="snapshot")
        assert len(snapshots) == 1
        assert snapshots[0]["event_id"] == event_id

        intents = self.client._storage.query_events(event_type="span", kind="intent")
        assert len(intents) == 1
        intent = intents[0]
        assert intent["name"] == "service-restart"
        assert intent["meta"]["semantic"]["type"] == "intent"
        assert intent["meta"]["semantic"]["intent"] == "service-restart"
        assert intent["meta"]["semantic"]["inputs"]["service"] == "test-svc"
        assert intent["meta"]["semantic"]["inputs"]["db_path"] == "/tmp/test.db"
        assert intent["meta"]["semantic"]["expected"]["result"] == "service_ready"
        assert intent["trace_id"]  # should have a real trace_id
