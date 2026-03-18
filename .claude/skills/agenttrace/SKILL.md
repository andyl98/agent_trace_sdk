---
name: agenttrace
description: Observability toolkit for agenttrace-instrumented applications — query telemetry, diagnose errors, analyze performance, inspect traces, and compare deployments. Auto-loads when working with telemetry, traces, errors, metrics, or performance. Provides workflows for diagnosis, error reports, performance checks, trace inspection, and snapshot diffs.
user-invocable: true
---

# AgentTrace Observability SDK

AgentTrace provides machine-readable telemetry for AI-operated applications. All telemetry is stored locally in SQLite (`.agenttrace.db`) and queryable via CLI or the `QueryAPI`.

## Finding the database

Look for `.agenttrace.db` files in the working directory or subdirectories. The `--db` flag on the CLI sets the path.

For the split demo app repo (`demo_app`), the app itself is SDK-free. Check for the DB at `../agent_trace_sdk/demo/runtime/merchant-ops/.agenttrace.db`.

## CLI quick reference

All commands output JSON. Base invocation: `agenttrace --db <path> <command> [flags]`

| Command | Purpose | Key flags |
|:--------|:--------|:----------|
| `traces` | List/filter request traces | `--path`, `--status`, `--min-duration`, `--since`, `--sort`, `--limit` |
| `trace <id>` | Single trace with full span tree + errors | — |
| `spans` | List/filter spans | `--kind`, `--min-duration`, `--name`, `--since`, `--sort`, `--limit` |
| `errors` | Group or list errors | `--group-by`, `--fingerprint`, `--path`, `--since` |
| `stats <path>` | Endpoint success/error rate | `--since`, `--bucket` |
| `snapshots` | List deployment snapshots | `--limit` |
| `diff <left> <right>` | Compare two snapshots | — |
| `compare` | Compare metric across time windows | `--metric`, `--window1`, `--window2` |
| `correlate` | Find changes around error spikes | `--since`, `--window` |
| `sql "<query>"` | Raw SQL query | — |

For full CLI details (all flags, defaults, examples): See [cli-reference.md](cli-reference.md)

## Workflows

Choose the workflow that matches the task:

| Task | Workflow | When to use |
|:-----|:---------|:------------|
| **Full diagnosis** | [diagnose.md](diagnose.md) | Root-cause analysis: errors + slow traces + deployment correlation |
| **Error report** | [error-report.md](error-report.md) | Comprehensive error summary grouped by fingerprint, status, type |
| **Performance check** | [perf-check.md](perf-check.md) | Latency analysis, bottleneck spans, slow DB/HTTP calls |
| **Trace inspection** | [trace-inspect.md](trace-inspect.md) | Deep-dive into a single trace: span waterfall, timing, errors |
| **Snapshot diff** | [snapshot-diff.md](snapshot-diff.md) | Compare deployments: dependency, config, and git changes |

## Key concepts

- **Time windows**: Relative (`1h`, `24h`, `7d`) or absolute (ISO 8601 timestamps)
- **Error fingerprinting**: Dynamic values (UUIDs, integers, hex) normalized to `<X>` then hashed — same logical error gets same fingerprint
- **DB views**: `v_traces`, `v_spans`, `v_errors`, `v_metrics`, `v_snapshots`
- **Span kinds**: `db`, `http_client`, `compute`, `intent`, `decision`, `invariant`, `fallback`


## Important note
- Never use `python -m agenttrace`, always invoke it directly with `agenttrace`