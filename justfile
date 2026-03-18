set dotenv-load := false

venv := ".venv/bin"
upstream_repo := "../opaque_carrier_api"
trace_db := "merchant_ops/.agenttrace.db"

default:
    @just --list

install:
    uv venv .venv 2>/dev/null || true
    uv pip install --python {{ venv }}/python -e ".[demo]"
    uv pip install --python {{ venv }}/python -e "{{ upstream_repo }}"

seed:
    {{ venv }}/python -m merchant_ops.seed

clean-telemetry:
    rm -f {{ trace_db }}
    @echo "Telemetry cleaned"

start PORT="8000":
    #!/usr/bin/env bash
    set -e

    {{ venv }}/python -m opaque_carrier_api.server &
    UPSTREAM_PID=$!

    UPSTREAM_URL=http://127.0.0.1:8001 \
    JWT_ALGORITHM=HS256 \
    AGENTTRACE_DB_PATH="{{ trace_db }}" \
    {{ venv }}/python -m uvicorn merchant_ops.app:app --host 127.0.0.1 --port {{ PORT }} &
    APP_PID=$!

    echo ""
    echo "Upstream carrier API  → http://localhost:8001  (pid $UPSTREAM_PID)"
    echo "Merchant Ops Console  → http://localhost:{{ PORT }}  (pid $APP_PID)"
    echo "AgentTrace DB         → {{ trace_db }}"
    echo ""
    echo "Press Ctrl-C to stop both."

    trap "kill $UPSTREAM_PID $APP_PID 2>/dev/null; exit 0" INT TERM
    wait

stop:
    pkill -f "opaque_carrier_api.server" 2>/dev/null || true
    pkill -f "uvicorn merchant_ops.app:app" 2>/dev/null || true
    @echo "Stopped demo services"

traces *ARGS:
    {{ venv }}/agenttrace --db {{ trace_db }} traces --sort duration_ms --desc {{ ARGS }}

trace TRACE_ID:
    {{ venv }}/agenttrace --db {{ trace_db }} trace {{ TRACE_ID }}

slow-spans *ARGS:
    {{ venv }}/agenttrace --db {{ trace_db }} spans --kind db --sort duration_ms --desc {{ ARGS }}

errors *ARGS:
    {{ venv }}/agenttrace --db {{ trace_db }} errors --group-by fingerprint {{ ARGS }}

stats PATH *ARGS:
    {{ venv }}/agenttrace --db {{ trace_db }} stats {{ PATH }} {{ ARGS }}

monitor PORT="8787":
    #!/usr/bin/env bash
    set -e
    URL="http://127.0.0.1:{{ PORT }}"
    (sleep 1; {{ venv }}/python -m webbrowser "$URL" >/dev/null 2>&1 || true) &
    {{ venv }}/python -m agenttrace.monitor --db {{ trace_db }} --host 127.0.0.1 --port {{ PORT }}

loadgen *ARGS:
    {{ venv }}/python -m merchant_ops.loadgen {{ ARGS }}

diagnose:
    #!/usr/bin/env bash
    echo "=== Slowest Traces ==="
    {{ venv }}/agenttrace --db {{ trace_db }} traces --sort duration_ms --desc --limit 10
    echo ""
    echo "=== Error Groups ==="
    {{ venv }}/agenttrace --db {{ trace_db }} errors --group-by fingerprint
    echo ""
    echo "=== Endpoint Stats ==="
    for path in /api/dashboard/orders /api/shipments/quote /api/auth/login; do
        echo "--- $path ---"
        {{ venv }}/agenttrace --db {{ trace_db }} stats "$path" --since 1h
    done

test:
    {{ venv }}/python -m pytest tests/ -v

docs:
    open docs/index.html