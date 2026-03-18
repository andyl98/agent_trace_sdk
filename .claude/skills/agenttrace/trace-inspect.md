# Trace Inspect

Deep-dive into a single trace.

**Database path:** Find `.agenttrace.db` in the working directory or subdirectories. For the split demo, check `../agent_trace_sdk/demo/runtime/merchant-ops/.agenttrace.db`.

## Steps

1. Run `agenttrace trace <trace_id>` to get the full trace with its span tree and errors.

2. Analyze and present:
   - **Request overview**: method, path, status, total duration
   - **Span waterfall**: list spans in order showing name, kind, duration, and percentage of total time
   - **Critical path**: which span(s) dominate the request time
   - **Errors**: any errors that occurred, with type and message
   - **Anomalies**: unusually slow spans, failed child operations, or missing expected spans
