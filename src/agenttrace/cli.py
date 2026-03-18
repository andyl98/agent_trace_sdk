"""CLI entry point for agenttrace — all commands output JSON for agent consumption."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .query import QueryAPI
from .storage import Storage


def _json_out(data: Any) -> None:
    """Pretty-print JSON to stdout."""
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttrace",
        description="Query agent-trace telemetry (JSON output)",
    )
    parser.add_argument(
        "--db", default="/Users/tianacui/git/agent_trace_sdk/merchant_ops/.agenttrace.db", help="Path to agenttrace database"
    )
    sub = parser.add_subparsers(dest="command")

    # ---- traces -------------------------------------------------------
    p = sub.add_parser("traces", help="List/filter traces")
    p.add_argument("--path", help="Filter by HTTP path (substring match)")
    p.add_argument("--method", help="Filter by HTTP method")
    p.add_argument("--status", help="Filter by status (ok/error)")
    p.add_argument("--min-duration", type=float, help="Min duration in ms")
    p.add_argument("--since", help="Time window, e.g. 1h, 24h, 7d")
    p.add_argument("--until", help="Until timestamp (ISO)")
    p.add_argument("--sort", default="timestamp", help="Sort column")
    p.add_argument("--desc", action="store_true", default=True)
    p.add_argument("--asc", action="store_true")
    p.add_argument("--limit", type=int, default=20)

    # ---- trace (single) -----------------------------------------------
    p = sub.add_parser("trace", help="Get a single trace with span tree")
    p.add_argument("trace_id", help="Trace ID")

    # ---- spans --------------------------------------------------------
    p = sub.add_parser("spans", help="List/filter spans")
    p.add_argument("--trace-id", help="Filter by trace ID")
    p.add_argument("--kind", help="Filter by kind (db, http_client, compute)")
    p.add_argument("--path", help="Filter by parent HTTP path")
    p.add_argument("--semantic-type", help="Filter by semantic type (intent, decision, invariant, fallback)")
    p.add_argument("--semantic-name", help="Filter by semantic label/name")
    p.add_argument("--min-duration", type=float, help="Min duration in ms")
    p.add_argument("--name", help="Filter by name (substring)")
    p.add_argument("--since", help="Time window")
    p.add_argument("--sort", default="duration_ms")
    p.add_argument("--desc", action="store_true", default=True)
    p.add_argument("--asc", action="store_true")
    p.add_argument("--limit", type=int, default=20)

    # ---- span-stats ---------------------------------------------------
    p = sub.add_parser("span-stats", help="Duration stats for spans or semantic actions")
    p.add_argument("--kind", help="Filter by kind (db, http_client, intent, decision, ...)")
    p.add_argument("--name", help="Filter by span name (substring)")
    p.add_argument("--path", help="Filter by parent HTTP path")
    p.add_argument("--semantic-type", help="Filter by semantic type (intent, decision, invariant, fallback)")
    p.add_argument("--semantic-name", help="Filter by semantic label/name")
    p.add_argument("--since", default="24h", help="Time window")
    p.add_argument("--bucket", help="Time bucket, e.g. 1h, 5m")

    # ---- errors -------------------------------------------------------
    p = sub.add_parser("errors", help="Group/list errors")
    p.add_argument(
        "--group-by",
        default="fingerprint",
        choices=["fingerprint", "status_code", "error_type"],
        help="Grouping dimension",
    )
    p.add_argument("--path", help="Filter by endpoint path")
    p.add_argument("--since", help="Time window")
    p.add_argument("--sort", default="count")
    p.add_argument("--desc", action="store_true", default=True)
    p.add_argument("--asc", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--fingerprint", help="Get examples for a specific fingerprint")

    # ---- stats --------------------------------------------------------
    p = sub.add_parser("stats", help="Endpoint success/error rate")
    p.add_argument("path", help="Endpoint path")
    p.add_argument("--since", default="24h")
    p.add_argument("--bucket", help="Time bucket, e.g. 1h, 5m")

    # ---- snapshots ----------------------------------------------------
    p = sub.add_parser("snapshots", help="List deployment snapshots")
    p.add_argument("--limit", type=int, default=10)

    # ---- diff ---------------------------------------------------------
    p = sub.add_parser("diff", help="Diff two snapshots")
    p.add_argument("left", help="Left snapshot ID")
    p.add_argument("right", help="Right snapshot ID")

    # ---- compare ------------------------------------------------------
    p = sub.add_parser("compare", help="Compare metric between two time windows")
    p.add_argument("--metric", required=True, help="Metric name")
    p.add_argument("--window1", required=True, help="start/end ISO, slash-separated")
    p.add_argument("--window2", required=True, help="start/end ISO, slash-separated")

    # ---- correlate ----------------------------------------------------
    p = sub.add_parser("correlate", help="Find what changed around error spikes")
    p.add_argument("--since", help="Time window to search")
    p.add_argument("--window", default="2h", help="How far back to look for snapshots")

    # ---- sql ----------------------------------------------------------
    p = sub.add_parser("sql", help="Run raw SQL query")
    p.add_argument("query", help="SQL query string")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    storage = Storage(args.db)
    storage.initialize()
    api = QueryAPI(storage)

    try:
        _dispatch(args, api)
    finally:
        storage.close()


def _dispatch(args: argparse.Namespace, api: QueryAPI) -> None:
    cmd = args.command

    if cmd == "traces":
        desc = not args.asc
        result = api.find_traces(
            path=args.path,
            method=args.method,
            status=args.status,
            min_duration=args.min_duration,
            since=args.since,
            until=args.until,
            sort=args.sort,
            desc=desc,
            limit=args.limit,
        )
        _json_out(result)

    elif cmd == "trace":
        result = api.get_trace(args.trace_id)
        if result is None:
            _json_out({"error": f"Trace {args.trace_id} not found"})
            sys.exit(1)
        _json_out(result)

    elif cmd == "spans":
        desc = not args.asc
        result = api.find_spans(
            trace_id=args.trace_id,
            kind=args.kind,
            path=args.path,
            semantic_type=args.semantic_type,
            semantic_name=args.semantic_name,
            min_duration=args.min_duration,
            name=args.name,
            since=args.since,
            sort=args.sort,
            desc=desc,
            limit=args.limit,
        )
        _json_out(result)

    elif cmd == "span-stats":
        result = api.span_stats(
            kind=args.kind,
            name=args.name,
            path=args.path,
            semantic_type=args.semantic_type,
            semantic_name=args.semantic_name,
            since=args.since,
            bucket=args.bucket,
        )
        _json_out(result)

    elif cmd == "errors":
        if args.fingerprint:
            result = api.get_error_examples(args.fingerprint, limit=args.limit)
        else:
            desc = not args.asc
            result = api.group_errors(
                group_by=args.group_by,
                path=args.path,
                since=args.since,
                sort=args.sort,
                desc=desc,
                limit=args.limit,
            )
        _json_out(result)

    elif cmd == "stats":
        result = api.stats(args.path, since=args.since, bucket=args.bucket)
        _json_out(result)

    elif cmd == "snapshots":
        result = api.list_snapshots(limit=args.limit)
        _json_out(result)

    elif cmd == "diff":
        result = api.diff_snapshots(args.left, args.right)
        _json_out(result)

    elif cmd == "compare":
        w1_parts = args.window1.split("/")
        w2_parts = args.window2.split("/")
        if len(w1_parts) != 2 or len(w2_parts) != 2:
            _json_out({"error": "Windows must be start/end ISO separated by /"})
            sys.exit(1)
        result = api.compare_windows(
            args.metric,
            w1_parts[0], w1_parts[1],
            w2_parts[0], w2_parts[1],
        )
        _json_out(result)

    elif cmd == "correlate":
        result = api.correlate(since=args.since, window=args.window)
        _json_out(result)

    elif cmd == "sql":
        result = api.sql(args.query)
        _json_out(result)

    else:
        _json_out({"error": f"Unknown command: {cmd}"})
        sys.exit(1)
