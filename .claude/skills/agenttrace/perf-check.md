# Performance Check

Analyze performance for a specific endpoint or the entire application.

**Endpoint:** If specified, add `--path <endpoint>` to trace/span queries.

**Database path:** Find `.agenttrace.db` in the working directory or subdirectories. For the split demo, check `../agent_trace_sdk/demo/runtime/merchant-ops/.agenttrace.db`.

**Time window:** Default to `1h` unless specified.

## Steps

1. **Slow traces** — `agenttrace traces --sort duration_ms --desc --limit 10 --since <window>` (add `--path <endpoint>` if specified)

2. **Slow spans** — `agenttrace spans --sort duration_ms --desc --limit 10 --since <window>`

3. **DB bottlenecks** — `agenttrace spans --kind db --sort duration_ms --desc --limit 10 --since <window>`

4. **HTTP client bottlenecks** — `agenttrace spans --kind http_client --sort duration_ms --desc --limit 5 --since <window>`

5. **Endpoint stats** — If an endpoint is specified, run `agenttrace stats <path> --since <window>`

6. **Deep dive** — For the slowest trace, run `agenttrace trace <trace_id>` for the full span breakdown.

## Output format

Present findings:
- **Latency summary**: p50/p95/p99 if enough data, or top-N slowest requests
- **Bottleneck analysis**: which span kinds (db, http_client, compute) dominate latency
- **Specific slow operations**: individual queries or calls with their durations
- **Recommendations**: indexing suggestions, caching opportunities, or upstream issues
