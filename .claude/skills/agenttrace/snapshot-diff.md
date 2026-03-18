# Snapshot Diff

Compare deployment snapshots to understand what changed between versions.

**Database path:** Find `.agenttrace.db` in the working directory or subdirectories. For the split demo, check `../agent_trace_sdk/demo/runtime/merchant-ops/.agenttrace.db`.

## Steps

1. **List snapshots** — `agenttrace snapshots --limit 10` to show recent deployments.

2. **Diff** — If two snapshot IDs are provided, run `agenttrace diff <left> <right>`. Otherwise, diff the two most recent snapshots from step 1.

3. **Analyze changes** — From the diff output, categorize:
   - **Dependency changes**: packages added, removed, or version-bumped
   - **Environment changes**: config values that differ
   - **Git changes**: commits between the two snapshots

## Output format

Present a clear summary:
- **What changed**: concise list of dependency, config, and code changes
- **Risk assessment**: which changes are most likely to affect behavior
- **Correlation**: if errors spiked after a deployment, highlight the most suspicious changes
