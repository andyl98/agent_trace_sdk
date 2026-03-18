"""Tests for the query API and CLI."""

from __future__ import annotations

import json
import os
import tempfile
from io import StringIO

import pytest

from agenttrace import AgentTrace, Event
from agenttrace.context import trace_context
from agenttrace.query import QueryAPI
from agenttrace.storage import Storage


@pytest.fixture
def db_path():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    yield f.name
    os.unlink(f.name)


@pytest.fixture
def storage(db_path):
    s = Storage(db_path)
    s.initialize()
    yield s
    s.close()


@pytest.fixture
def api(storage):
    return QueryAPI(storage)


@pytest.fixture
def seeded_storage(storage):
    """Seed with some realistic events."""
    # Two traces: one fast, one slow
    fast_trace = Event.trace("GET /api/health", kind="http", meta={"http": {"path": "/api/health", "method": "GET"}})
    fast_trace.status = "ok"
    fast_trace.duration_ms = 12.0
    storage.write_event(fast_trace)

    slow_trace = Event.trace("GET /api/dashboard", kind="http", meta={"http": {"path": "/api/dashboard", "method": "GET"}})
    slow_trace.status = "ok"
    slow_trace.duration_ms = 4200.0
    storage.write_event(slow_trace)

    # Spans for the slow trace
    db_span = Event.span(slow_trace.trace_id, "SELECT orders", kind="db", meta={"query": "SELECT * FROM orders WHERE merchant_id = ?"})
    db_span.duration_ms = 3800.0
    db_span.status = "ok"
    storage.write_event(db_span)

    compute_span = Event.span(slow_trace.trace_id, "aggregate", kind="compute")
    compute_span.duration_ms = 380.0
    compute_span.status = "ok"
    storage.write_event(compute_span)

    intent_span = Event.span(
        fast_trace.trace_id,
        "Load health check",
        kind="intent",
        meta={"semantic": {"type": "intent", "intent": "Load health check"}},
    )
    intent_span.duration_ms = 5.0
    intent_span.status = "ok"
    storage.write_event(intent_span)

    decision_span = Event.span(
        fast_trace.trace_id,
        "Choose health backend",
        kind="decision",
        meta={
            "semantic": {
                "type": "decision",
                "decision": "Choose health backend",
                "chosen": "local",
            }
        },
    )
    decision_span.duration_ms = 0.0
    decision_span.status = "ok"
    storage.write_event(decision_span)

    # Error trace
    err_trace = Event.trace("POST /api/submit", kind="http", meta={"http": {"path": "/api/submit", "method": "POST"}})
    err_trace.status = "error"
    err_trace.duration_ms = 150.0
    storage.write_event(err_trace)

    # Errors with same fingerprint
    for i in range(5):
        err = Event.error(
            "ValidationError",
            f"field 'company_name' expected string, got null (request {i})",
            trace_id=err_trace.trace_id,
            status_code=422,
        )
        storage.write_event(err)

    # A different error
    err2 = Event.error("TimeoutError", "upstream timed out after 30s", status_code=503)
    storage.write_event(err2)

    # Snapshots
    snap1 = Event.snapshot(
        git_sha="aaa111",
        dependencies={"fastapi": "0.100.0", "pydantic": "2.0.0"},
        runtime="python 3.12.0",
        env_vars={"JWT_ALGORITHM": "HS256", "DB_HOST": "localhost"},
    )
    storage.write_event(snap1)

    snap2 = Event.snapshot(
        git_sha="bbb222",
        dependencies={"fastapi": "0.100.0", "pydantic": "2.5.0"},
        runtime="python 3.12.0",
        env_vars={"DB_HOST": "localhost"},
    )
    storage.write_event(snap2)

    return storage, {
        "fast_trace": fast_trace,
        "slow_trace": slow_trace,
        "err_trace": err_trace,
        "snap1": snap1,
        "snap2": snap2,
    }


class TestQueryTraces:
    def test_find_all(self, seeded_storage):
        storage, ids = seeded_storage
        api = QueryAPI(storage)
        traces = api.find_traces()
        assert len(traces) == 3

    def test_filter_by_path(self, seeded_storage):
        storage, ids = seeded_storage
        api = QueryAPI(storage)
        traces = api.find_traces(path="/api/dashboard")
        assert len(traces) == 1
        assert "dashboard" in traces[0]["name"]

    def test_filter_by_min_duration(self, seeded_storage):
        storage, ids = seeded_storage
        api = QueryAPI(storage)
        traces = api.find_traces(min_duration=1000)
        assert len(traces) == 1
        assert traces[0]["duration_ms"] == 4200.0

    def test_sort_by_duration(self, seeded_storage):
        storage, ids = seeded_storage
        api = QueryAPI(storage)
        traces = api.find_traces(sort="duration_ms", desc=True)
        assert traces[0]["duration_ms"] >= traces[-1]["duration_ms"]


class TestQueryTrace:
    def test_get_with_spans(self, seeded_storage):
        storage, ids = seeded_storage
        api = QueryAPI(storage)
        trace = api.get_trace(ids["slow_trace"].trace_id)
        assert trace is not None
        assert len(trace["spans"]) == 2
        # DB span should be there
        db_spans = [s for s in trace["spans"] if s["kind"] == "db"]
        assert len(db_spans) == 1
        assert db_spans[0]["duration_ms"] == 3800.0

    def test_not_found(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        assert api.get_trace("nonexistent") is None


class TestQuerySpans:
    def test_find_slow_db(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        spans = api.find_spans(kind="db", min_duration=1000)
        assert len(spans) == 1
        assert spans[0]["name"] == "SELECT orders"

    def test_find_semantic_intent(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        spans = api.find_spans(semantic_type="intent", semantic_name="health")
        assert len(spans) == 1
        assert spans[0]["kind"] == "intent"
        assert spans[0]["meta"]["semantic"]["intent"] == "Load health check"

    def test_find_spans_by_path(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        spans = api.find_spans(path="/api/health", semantic_type="intent")
        assert len(spans) == 1
        assert spans[0]["name"] == "Load health check"


class TestQueryErrors:
    def test_group_by_fingerprint(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        groups = api.group_errors(group_by="fingerprint")
        # Should have 2 groups (ValidationError x5 and TimeoutError x1)
        assert len(groups) == 2
        # Most frequent first
        assert groups[0]["cnt"] == 5

    def test_group_by_status_code(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        groups = api.group_errors(group_by="status_code")
        codes = {g["group_key"] for g in groups}
        assert 422 in codes or "422" in codes

    def test_get_examples(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        groups = api.group_errors(group_by="fingerprint")
        fp = groups[0]["group_key"]
        examples = api.get_error_examples(fp, limit=3)
        assert len(examples) == 3

    def test_filter_by_path(self, seeded_storage):
        storage, ids = seeded_storage
        api = QueryAPI(storage)
        groups = api.group_errors(path="/api/submit")
        # Only ValidationErrors are linked to the submit trace
        assert len(groups) == 1
        assert groups[0]["cnt"] == 5


class TestStats:
    def test_endpoint_stats(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        result = api.stats("/api/submit", since="24h")
        assert result["total"] == 1
        assert result["errors"] == 1
        assert result["error_rate"] == 100.0

    def test_healthy_endpoint(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        result = api.stats("/api/health", since="24h")
        assert result["total"] == 1
        assert result["success_rate"] == 100.0
        assert result["p50_duration_ms"] == 12.0
        assert result["p95_duration_ms"] == 12.0

    def test_span_stats_for_semantic_intent(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        result = api.span_stats(semantic_type="intent", path="/api/health", since="24h")
        assert result["total"] == 1
        assert result["avg_duration_ms"] == 5.0
        assert result["p50_duration_ms"] == 5.0


class TestSnapshots:
    def test_list(self, seeded_storage):
        storage, _ = seeded_storage
        api = QueryAPI(storage)
        snaps = api.list_snapshots()
        assert len(snaps) == 2

    def test_diff(self, seeded_storage):
        storage, ids = seeded_storage
        api = QueryAPI(storage)
        diff = api.diff_snapshots(ids["snap1"].event_id, ids["snap2"].event_id)
        # pydantic version changed
        assert "pydantic" in diff["dependencies_changed"]
        assert diff["dependencies_changed"]["pydantic"]["from"] == "2.0.0"
        assert diff["dependencies_changed"]["pydantic"]["to"] == "2.5.0"
        # JWT_ALGORITHM was removed
        assert "JWT_ALGORITHM" in diff["env_changed"]
        assert diff["env_changed"]["JWT_ALGORITHM"]["to"] is None
        # Git changed
        assert diff["git_changed"]["from"] == "aaa111"
        assert diff["git_changed"]["to"] == "bbb222"


class TestCLI:
    def test_traces_command(self, seeded_storage, capsys, db_path):
        storage, _ = seeded_storage
        from agenttrace.cli import main
        main(["--db", db_path, "traces", "--limit", "5"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert len(data) == 3

    def test_trace_command(self, seeded_storage, capsys, db_path):
        storage, ids = seeded_storage
        from agenttrace.cli import main
        main(["--db", db_path, "trace", ids["slow_trace"].trace_id])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert len(data["spans"]) == 2

    def test_errors_command(self, seeded_storage, capsys, db_path):
        storage, _ = seeded_storage
        from agenttrace.cli import main
        main(["--db", db_path, "errors", "--group-by", "fingerprint"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert len(data) == 2

    def test_stats_command(self, seeded_storage, capsys, db_path):
        storage, _ = seeded_storage
        from agenttrace.cli import main
        main(["--db", db_path, "stats", "/api/submit"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "error_rate" in data
        assert "p95_duration_ms" in data

    def test_spans_semantic_filter_command(self, seeded_storage, capsys, db_path):
        storage, _ = seeded_storage
        from agenttrace.cli import main
        main(["--db", db_path, "spans", "--semantic-type", "intent", "--path", "/api/health"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert len(data) == 1
        assert data[0]["kind"] == "intent"

    def test_span_stats_command(self, seeded_storage, capsys, db_path):
        storage, _ = seeded_storage
        from agenttrace.cli import main
        main(["--db", db_path, "span-stats", "--semantic-type", "intent", "--path", "/api/health"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["total"] == 1
        assert data["p50_duration_ms"] == 5.0

    def test_snapshots_command(self, seeded_storage, capsys, db_path):
        storage, _ = seeded_storage
        from agenttrace.cli import main
        main(["--db", db_path, "snapshots"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert len(data) == 2

    def test_diff_command(self, seeded_storage, capsys, db_path):
        storage, ids = seeded_storage
        from agenttrace.cli import main
        main(["--db", db_path, "diff", ids["snap1"].event_id, ids["snap2"].event_id])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "dependencies_changed" in data

    def test_sql_command(self, seeded_storage, capsys, db_path):
        storage, _ = seeded_storage
        from agenttrace.cli import main
        main(["--db", db_path, "sql", "SELECT count(*) AS cnt FROM events"])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data[0]["cnt"] > 0
