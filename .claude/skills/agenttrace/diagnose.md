# Diagnose

Multi-step root-cause analysis. Use the agenttrace CLI for each step.

**Database path:** Find `.agenttrace.db` in the working directory or subdirectories. For the split demo, check `../agent_trace_sdk/demo/runtime/merchant-ops/.agenttrace.db`.

**Time window:** Default to `1h` unless specified.

## Steps

1. **Error summary** — `agenttrace errors --group-by fingerprint --since <window> --limit 10`

2. **Slow traces** — `agenttrace traces --sort duration_ms --desc --limit 10 --since <window>`

3. **Slow spans** — `agenttrace spans --sort duration_ms --desc --limit 10 --since <window>`

4. **Endpoint stats** — For endpoints that appear in errors or slow traces, run `agenttrace stats <path> --since <window>`

5. **Correlation** — `agenttrace correlate --since <window>` to check if recent deployments or config changes coincide with the issues.

6. **Drill down** — For the top error fingerprint, run `agenttrace errors --fingerprint <fp> --limit 3` for concrete examples with stack traces.

## Output format

Present findings as a structured report:
- **Error hotspots**: top errors by frequency with example messages
- **Performance bottlenecks**: slowest traces and which spans dominate
- **Root cause hints**: deployment/config changes that correlate
- **Recommended next steps**: specific actions to investigate or fix
