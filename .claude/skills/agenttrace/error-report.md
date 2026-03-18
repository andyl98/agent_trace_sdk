# Error Report

Comprehensive error summary from telemetry data.

**Database path:** Find `.agenttrace.db` in the working directory or subdirectories. For the split demo, check `../agent_trace_sdk/demo/runtime/merchant-ops/.agenttrace.db`.

**Time window:** Default to `24h` unless specified.

## Steps

1. **Group by fingerprint** — `agenttrace errors --group-by fingerprint --since <window> --limit 20`

2. **Group by status code** — `agenttrace errors --group-by status_code --since <window>`

3. **Group by error type** — `agenttrace errors --group-by error_type --since <window>`

4. **Examples** — For each of the top 3 fingerprints, run `agenttrace errors --fingerprint <fp> --limit 3` for concrete examples with stack traces.

5. **Affected endpoints** — For endpoints in error examples, run `agenttrace stats <path> --since <window>` to quantify error rates.

## Output format

Present as a structured report:
- **Summary**: total unique error types, total occurrences
- **Top errors**: table of fingerprint, error type, count, example message
- **Stack traces**: key excerpts from the most impactful errors
- **Affected endpoints**: which endpoints have the highest error rates
- **Recommendations**: suggested investigation steps or fixes
