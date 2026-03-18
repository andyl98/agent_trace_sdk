# CLI Reference

All commands output JSON. Base invocation: `agenttrace --db <path> <command> [flags]`

## traces — List/filter traces

```
agenttrace --db <db> traces [--path <substr>] [--method GET|POST|...] [--status ok|error]
    [--min-duration <ms>] [--since <window>] [--until <iso>]
    [--sort <col>] [--desc|--asc] [--limit <n>]
```

Defaults: `--sort timestamp --desc --limit 20`

## trace — Single trace with full span tree

```
agenttrace --db <db> trace <trace_id>
```

Returns the trace, its nested span tree, and associated errors.

## spans — List/filter spans

```
agenttrace --db <db> spans [--trace-id <id>] [--kind db|http_client|compute]
    [--min-duration <ms>] [--name <substr>] [--since <window>]
    [--sort <col>] [--desc|--asc] [--limit <n>]
```

Defaults: `--sort duration_ms --desc --limit 20`

## errors — Group or list errors

```
# Group errors
agenttrace --db <db> errors [--group-by fingerprint|status_code|error_type]
    [--path <substr>] [--since <window>]
    [--sort <col>] [--desc|--asc] [--limit <n>]

# Get examples for a specific fingerprint
agenttrace --db <db> errors --fingerprint <fp> [--limit <n>]
```

Defaults: `--group-by fingerprint --sort count --desc --limit 20`

## stats — Endpoint success/error rate

```
agenttrace --db <db> stats <path> [--since <window>] [--bucket <interval>]
```

Defaults: `--since 24h`

## snapshots — List deployment snapshots

```
agenttrace --db <db> snapshots [--limit <n>]
```

## diff — Compare two snapshots

```
agenttrace --db <db> diff <left_id> <right_id>
```

Shows dependency changes, environment changes, and git diff between deployments.

## compare — Compare metric across time windows

```
agenttrace --db <db> compare --metric <name> --window1 <start>/<end> --window2 <start>/<end>
```

Windows are ISO timestamps separated by `/`.

## correlate — Find what changed around error spikes

```
agenttrace --db <db> correlate [--since <window>] [--window <lookback>]
```

Defaults: `--window 2h`

## sql — Raw SQL query

```
agenttrace --db <db> sql "<query>"
```

### QPS / traffic analysis

The built-in commands don't provide QPS or per-minute traffic breakdowns. For QPS, throughput, or traffic-pattern questions, use `sql` with time-bucketed aggregation queries against the database views.

**Per-minute request rate (all endpoints):**
```
agenttrace --db <db> sql "SELECT strftime('%Y-%m-%dT%H:%M', started_at) as minute, count(*) as requests FROM v_traces GROUP BY minute ORDER BY minute"
```

**Per-minute rate for a specific endpoint or span name:**
```
agenttrace --db <db> sql "SELECT strftime('%Y-%m-%dT%H:%M', started_at) as minute, count(*) as calls FROM v_spans WHERE name LIKE '%/api/v1/quote%' GROUP BY minute ORDER BY minute"
```

**Average QPS over the full window:**
```
agenttrace --db <db> sql "SELECT count(*) as total, (julianday(max(started_at)) - julianday(min(started_at))) * 86400 as window_seconds, count(*) * 1.0 / ((julianday(max(started_at)) - julianday(min(started_at))) * 86400) as avg_qps FROM v_traces"
```

**Per-minute rate filtered by time window:**
```
agenttrace --db <db> sql "SELECT strftime('%Y-%m-%dT%H:%M', started_at) as minute, count(*) as requests FROM v_traces WHERE started_at >= datetime('now', '-1 hour') GROUP BY minute ORDER BY minute"
```

These queries work on both `v_traces` (top-level requests) and `v_spans` (individual operations). Use `v_traces` for endpoint-level QPS and `v_spans` for upstream/downstream call rates. Add `WHERE` clauses with `name LIKE`, `kind =`, or time filters as needed.

## Database views

| View | Contents |
|:-----|:---------|
| `v_traces` | trace events |
| `v_spans` | span events |
| `v_errors` | error events with fingerprint |
| `v_metrics` | metric events with value/tags |
| `v_snapshots` | snapshot events |

## QueryAPI (programmatic)

```python
from agenttrace import AgentTrace

tracer = AgentTrace(db_path=".agenttrace.db")
api = tracer.query()

api.find_traces(path="/api/foo", status="error", limit=10)
api.get_trace(trace_id)
api.find_spans(kind="db", min_duration=100)
api.group_errors(group_by="fingerprint")
api.get_error_examples(fingerprint)
api.stats("/api/foo", since="1h")
api.list_snapshots()
api.diff_snapshots(left_id, right_id)
api.compare_windows(metric, w1_start, w1_end, w2_start, w2_end)
api.correlate(since="1h", window="2h")
api.sql("SELECT ...")
```
