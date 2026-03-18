"""Local browser monitor for AgentTrace telemetry."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .query import QueryAPI
from .storage import Storage

_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentTrace Monitor</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1020;
      --panel: #141b2d;
      --panel-2: #1c2540;
      --border: #2b3557;
      --text: #e7ecff;
      --muted: #9aa7cc;
      --ok: #4ade80;
      --warn: #fbbf24;
      --error: #f87171;
      --accent: #60a5fa;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    a { color: var(--accent); }
    button {
      background: var(--accent);
      color: #08111f;
      border: none;
      border-radius: 8px;
      padding: 8px 12px;
      font-weight: 600;
      cursor: pointer;
    }
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      background: #0f1630;
      padding: 2px 6px;
      border-radius: 6px;
    }
    .app {
      display: grid;
      grid-template-rows: auto auto 1fr;
      min-height: 100vh;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 20px;
      border-bottom: 1px solid var(--border);
      background: rgba(11, 16, 32, 0.95);
      position: sticky;
      top: 0;
      z-index: 10;
      backdrop-filter: blur(10px);
    }
    .subtitle {
      color: var(--muted);
      font-size: 14px;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      padding: 16px 20px;
    }
    .card, .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
    }
    .card {
      padding: 14px 16px;
    }
    .card .label {
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }
    .card .value {
      font-size: 26px;
      font-weight: 700;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
      gap: 16px;
      padding: 0 20px 20px;
    }
    .stack {
      display: grid;
      gap: 16px;
      min-width: 0;
    }
    .panel {
      overflow: hidden;
      min-width: 0;
    }
    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      background: var(--panel-2);
    }
    .panel-header h2 {
      font-size: 16px;
      margin: 0;
    }
    .panel-body {
      padding: 0;
      overflow: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 640px;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(43, 53, 87, 0.6);
      text-align: left;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    tr.clickable { cursor: pointer; }
    tr.clickable:hover { background: rgba(96, 165, 250, 0.08); }
    tr.selected { background: rgba(96, 165, 250, 0.14); }
    .badge {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      gap: 6px;
      white-space: nowrap;
    }
    .status-ok { color: var(--ok); }
    .status-error { color: var(--error); }
    .muted { color: var(--muted); }
    .detail {
      padding: 16px;
      display: grid;
      gap: 14px;
    }
    .detail-block {
      background: #0f1630;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
    }
    .detail-block h3 {
      margin: 0 0 10px;
      font-size: 14px;
    }
    .kv {
      display: grid;
      grid-template-columns: 140px 1fr;
      gap: 8px 12px;
      font-size: 14px;
    }
    .kv .k { color: var(--muted); }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      line-height: 1.45;
    }
    .list {
      display: grid;
      gap: 8px;
    }
    .item {
      background: #0f1630;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .changes {
      display: grid;
      gap: 10px;
    }
    .change-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }
    .change-list {
      display: grid;
      gap: 8px;
    }
    .change-item {
      background: #0b132b;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
    }
    .change-item strong {
      display: block;
      margin-bottom: 4px;
    }
    .empty-state {
      color: var(--muted);
      font-size: 13px;
    }
    @media (max-width: 1200px) {
      .layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app">
    <div class="topbar">
      <div>
        <div style="font-size: 22px; font-weight: 700;">AgentTrace Monitor</div>
        <div class="subtitle">Grouped errors, recent traces, and slow spans from the saved SQLite trace store.</div>
      </div>
      <div class="toolbar">
        <div id="last-refresh" class="subtitle">Loading...</div>
        <button id="refresh-btn" type="button">Refresh</button>
      </div>
    </div>

    <div id="cards" class="cards"></div>

    <div class="layout">
      <div class="stack">
        <section class="panel">
          <div class="panel-header">
            <h2>Error Groups</h2>
            <span class="subtitle">Click a fingerprint for examples</span>
          </div>
          <div class="panel-body">
            <table>
              <thead>
                <tr>
                  <th>Fingerprint</th>
                  <th>Count</th>
                  <th>Latest</th>
                  <th>Sample</th>
                </tr>
              </thead>
              <tbody id="errors-body"></tbody>
            </table>
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <h2>Recent Traces</h2>
            <span class="subtitle">Click a trace to inspect spans and errors</span>
          </div>
          <div class="panel-body">
            <table>
              <thead>
                <tr>
                  <th>Trace</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Path</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody id="traces-body"></tbody>
            </table>
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <h2>Slow Spans</h2>
            <span class="subtitle">Sorted by duration</span>
          </div>
          <div class="panel-body">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Trace</th>
                </tr>
              </thead>
              <tbody id="spans-body"></tbody>
            </table>
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <h2>Snapshots</h2>
            <span class="subtitle">Click a deployment snapshot to compare it with the prior one</span>
          </div>
          <div class="panel-body">
            <table>
              <thead>
                <tr>
                  <th>Captured</th>
                  <th>Service</th>
                  <th>Git</th>
                  <th>Dependencies</th>
                  <th>Env Vars</th>
                </tr>
              </thead>
              <tbody id="snapshots-body"></tbody>
            </table>
          </div>
        </section>
      </div>

      <div class="stack">
        <section class="panel">
          <div class="panel-header">
            <h2>Trace Detail</h2>
            <span id="trace-detail-label" class="subtitle">Select a trace</span>
          </div>
          <div id="trace-detail" class="detail">
            <div class="detail-block">
              <pre>Select a trace from the table to inspect its spans and error events.</pre>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <h2>Error Examples</h2>
            <span id="error-detail-label" class="subtitle">Select an error group</span>
          </div>
          <div id="error-detail" class="detail">
            <div class="detail-block">
              <pre>Select an error fingerprint to see recent examples and stack traces.</pre>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <h2>Snapshot Detail</h2>
            <span id="snapshot-detail-label" class="subtitle">Select a snapshot</span>
          </div>
          <div id="snapshot-detail" class="detail">
            <div class="detail-block">
              <pre>Select a snapshot to inspect metadata and diffs against the previous deployment.</pre>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>

  <script>
    const state = {
      selectedTraceId: null,
      selectedFingerprint: null,
      selectedSnapshotId: null,
    };

    function fmtDuration(value) {
      if (value === null || value === undefined) return "-";
      return `${Number(value).toFixed(1)} ms`;
    }

    function fmtText(value) {
      if (value === null || value === undefined || value === "") return "-";
      return String(value);
    }

    function fmtTimestamp(value) {
      if (value === null || value === undefined || value === "") return "-";
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) return String(value);
      return parsed.toLocaleString();
    }

    function fmtJson(value) {
      return JSON.stringify(value ?? {}, null, 2);
    }

    function fmtShortId(value, length = 10) {
      if (value === null || value === undefined || value === "") return "-";
      return String(value).slice(0, length);
    }

    function statusBadge(status) {
      const safe = fmtText(status);
      const klass = safe === "ok" ? "status-ok" : (safe === "error" ? "status-error" : "");
      return `<span class="badge ${klass}">${safe}</span>`;
    }

    async function fetchJson(path) {
      const response = await fetch(path);
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      return response.json();
    }

    function renderCards(overview) {
      const cards = [
        ["Events", overview.counts.events],
        ["Traces", overview.counts.traces],
        ["Spans", overview.counts.spans],
        ["Errors", overview.counts.errors],
        ["Metrics", overview.counts.metrics],
        ["Snapshots", overview.counts.snapshots],
      ];
      const root = document.getElementById("cards");
      root.innerHTML = cards.map(([label, value]) => `
        <div class="card">
          <div class="label">${label}</div>
          <div class="value">${fmtText(value)}</div>
        </div>
      `).join("");
    }

    function renderErrors(groups) {
      const root = document.getElementById("errors-body");
      root.innerHTML = groups.map((group) => `
        <tr
          class="clickable ${state.selectedFingerprint === group.group_key ? "selected" : ""}"
          data-fingerprint="${group.group_key ?? ""}"
        >
          <td><code>${fmtText(group.group_key)}</code></td>
          <td>${fmtText(group.cnt)}</td>
          <td>${fmtTimestamp(group.latest)}</td>
          <td>${fmtText(group.sample_message)}</td>
        </tr>
      `).join("");
      root.querySelectorAll("tr").forEach((row) => {
        row.addEventListener("click", async () => {
          state.selectedFingerprint = row.dataset.fingerprint || null;
          renderErrors(groups);
          await loadErrorExamples();
        });
      });
    }

    function renderTraces(traces) {
      const root = document.getElementById("traces-body");
      root.innerHTML = traces.map((trace) => `
        <tr
          class="clickable ${state.selectedTraceId === trace.trace_id ? "selected" : ""}"
          data-trace-id="${trace.trace_id}"
        >
          <td>${fmtText(trace.name)}</td>
          <td>${statusBadge(trace.status)}</td>
          <td>${fmtDuration(trace.duration_ms)}</td>
          <td>${fmtText(trace.path)}</td>
          <td>${fmtTimestamp(trace.started_at)}</td>
        </tr>
      `).join("");
      root.querySelectorAll("tr").forEach((row) => {
        row.addEventListener("click", async () => {
          state.selectedTraceId = row.dataset.traceId;
          renderTraces(traces);
          await loadTraceDetail();
        });
      });
    }

    function renderSpans(spans) {
      const root = document.getElementById("spans-body");
      root.innerHTML = spans.map((span) => `
        <tr>
          <td>${fmtText(span.name)}</td>
          <td>${fmtText(span.kind)}</td>
          <td>${statusBadge(span.status)}</td>
          <td>${fmtDuration(span.duration_ms)}</td>
          <td><code>${fmtText(span.trace_id)}</code></td>
        </tr>
      `).join("");
    }

    function renderSnapshots(snapshots) {
      const root = document.getElementById("snapshots-body");
      root.innerHTML = snapshots.map((snapshot) => `
        <tr
          class="clickable ${state.selectedSnapshotId === snapshot.snapshot_id ? "selected" : ""}"
          data-snapshot-id="${snapshot.snapshot_id}"
        >
          <td>${fmtTimestamp(snapshot.timestamp)}</td>
          <td>${fmtText(snapshot.service_name)}</td>
          <td><code>${fmtShortId(snapshot.git_sha)}</code></td>
          <td>${fmtText(snapshot.dependency_count)}</td>
          <td>${fmtText(snapshot.env_var_count)}</td>
        </tr>
      `).join("");
      root.querySelectorAll("tr").forEach((row) => {
        row.addEventListener("click", async () => {
          state.selectedSnapshotId = row.dataset.snapshotId;
          renderSnapshots(snapshots);
          await loadSnapshotDetail();
        });
      });
    }

    function renderTraceDetail(trace) {
      const root = document.getElementById("trace-detail");
      const label = document.getElementById("trace-detail-label");
      if (!trace) {
        label.textContent = "Select a trace";
        root.innerHTML = `
          <div class="detail-block">
            <pre>Select a trace from the table to inspect its spans and error events.</pre>
          </div>
        `;
        return;
      }

      label.textContent = trace.trace_id;
      const spansHtml = (trace.spans || []).map((span) => `
        <div class="item">
          <div><strong>${fmtText(span.name)}</strong> <span class="muted">(${fmtText(span.kind)})</span></div>
          <div class="muted">${statusBadge(span.status)} ${fmtDuration(span.duration_ms)}</div>
          <pre>${fmtJson(span.meta)}</pre>
        </div>
      `).join("");

      const errorsHtml = (trace.errors || []).length
        ? (trace.errors || []).map((error) => `
            <div class="item">
              <div><strong>${fmtText(error.name)}</strong> <span class="muted">${fmtTimestamp(error.timestamp)}</span></div>
              <pre>${fmtJson(error.meta)}</pre>
            </div>
          `).join("")
        : `<div class="item"><div class="muted">No errors for this trace.</div></div>`;

      root.innerHTML = `
        <div class="detail-block">
          <h3>Trace Summary</h3>
          <div class="kv">
            <div class="k">Name</div><div>${fmtText(trace.name)}</div>
            <div class="k">Status</div><div>${statusBadge(trace.status)}</div>
            <div class="k">Duration</div><div>${fmtDuration(trace.duration_ms)}</div>
            <div class="k">Method</div><div>${fmtText(trace.method)}</div>
            <div class="k">Path</div><div>${fmtText(trace.path)}</div>
            <div class="k">Status Code</div><div>${fmtText(trace.status_code)}</div>
            <div class="k">Started</div><div>${fmtTimestamp(trace.timestamp)}</div>
          </div>
        </div>
        <div class="detail-block">
          <h3>Trace Meta</h3>
          <pre>${fmtJson(trace.meta)}</pre>
        </div>
        <div class="detail-block">
          <h3>Spans (${(trace.spans || []).length})</h3>
          <div class="list">${spansHtml || '<div class="item muted">No spans</div>'}</div>
        </div>
        <div class="detail-block">
          <h3>Errors (${(trace.errors || []).length})</h3>
          <div class="list">${errorsHtml}</div>
        </div>
      `;
    }

    function renderErrorExamples(examples) {
      const root = document.getElementById("error-detail");
      const label = document.getElementById("error-detail-label");
      if (!state.selectedFingerprint) {
        label.textContent = "Select an error group";
        root.innerHTML = `
          <div class="detail-block">
            <pre>Select an error fingerprint to see recent examples and stack traces.</pre>
          </div>
        `;
        return;
      }
      label.textContent = state.selectedFingerprint;

      root.innerHTML = examples.length ? examples.map((error) => `
        <div class="detail-block">
          <h3>${fmtText(error.name)} <span class="muted">${fmtTimestamp(error.timestamp)}</span></h3>
          <div class="kv">
            <div class="k">Trace</div><div><code>${fmtText(error.trace_id)}</code></div>
            <div class="k">Span</div><div><code>${fmtText(error.span_id)}</code></div>
          </div>
          <pre>${fmtJson(error.meta)}</pre>
        </div>
      `).join("") : `
        <div class="detail-block">
          <pre>No recent examples found for this fingerprint.</pre>
        </div>
      `;
    }

    function renderChangeList(changes, formatter) {
      if (!changes.length) {
        return '<div class="empty-state">No changes detected.</div>';
      }
      return `<div class="change-list">${changes.map(formatter).join("")}</div>`;
    }

    function renderSnapshotDetail(snapshot) {
      const root = document.getElementById("snapshot-detail");
      const label = document.getElementById("snapshot-detail-label");
      if (!snapshot) {
        label.textContent = "Select a snapshot";
        root.innerHTML = `
          <div class="detail-block">
            <pre>Select a snapshot to inspect metadata and diffs against the previous deployment.</pre>
          </div>
        `;
        return;
      }

      const meta = snapshot.meta || {};
      const dependencies = Object.entries(meta.dependencies || {});
      const envVars = Object.entries(meta.env_vars || {});
      const diff = snapshot.diff || {};
      const dependencyChanges = Object.entries(diff.dependencies_changed || {});
      const envChanges = Object.entries(diff.env_changed || {});
      const gitChanged = diff.git_changed || null;
      const runtimeChanged = diff.runtime_changed || null;

      label.textContent = fmtShortId(snapshot.snapshot_id, 14);
      root.innerHTML = `
        <div class="detail-block">
          <h3>Snapshot Summary</h3>
          <div class="kv">
            <div class="k">Snapshot</div><div><code>${fmtText(snapshot.snapshot_id)}</code></div>
            <div class="k">Captured</div><div>${fmtTimestamp(snapshot.timestamp)}</div>
            <div class="k">Service</div><div>${fmtText(snapshot.service_name)}</div>
            <div class="k">Git SHA</div><div><code>${fmtText(snapshot.git_sha)}</code></div>
            <div class="k">Runtime</div><div>${fmtText(snapshot.runtime)}</div>
            <div class="k">Dependencies</div><div>${dependencies.length}</div>
            <div class="k">Env Vars</div><div>${envVars.length}</div>
          </div>
        </div>
        <div class="detail-block">
          <h3>Compared With Previous Snapshot</h3>
          ${snapshot.previous ? `
            <div class="kv">
              <div class="k">Previous Snapshot</div><div><code>${fmtText(snapshot.previous.snapshot_id)}</code></div>
              <div class="k">Captured</div><div>${fmtTimestamp(snapshot.previous.timestamp)}</div>
              <div class="k">Dependency Changes</div><div>${dependencyChanges.length}</div>
              <div class="k">Env Changes</div><div>${envChanges.length}</div>
              <div class="k">Git Changed</div><div>${gitChanged ? "Yes" : "No"}</div>
              <div class="k">Runtime Changed</div><div>${runtimeChanged ? "Yes" : "No"}</div>
            </div>
          ` : '<div class="empty-state">No earlier snapshot available for comparison.</div>'}
        </div>
        <div class="detail-block">
          <h3>Change Summary</h3>
          <div class="change-grid">
            <div class="change-item">
              <strong>Git</strong>
              ${gitChanged ? `<div><code>${fmtText(gitChanged.from)}</code> -> <code>${fmtText(gitChanged.to)}</code></div>` : '<div class="empty-state">No git SHA change detected.</div>'}
            </div>
            <div class="change-item">
              <strong>Runtime</strong>
              ${runtimeChanged ? `<div>${fmtText(runtimeChanged.from)} -> ${fmtText(runtimeChanged.to)}</div>` : '<div class="empty-state">No runtime change detected.</div>'}
            </div>
          </div>
        </div>
        <div class="detail-block">
          <h3>Dependency Changes (${dependencyChanges.length})</h3>
          ${renderChangeList(dependencyChanges, ([name, change]) => `
            <div class="change-item">
              <strong>${fmtText(name)}</strong>
              <div><code>${fmtText(change.from)}</code> -> <code>${fmtText(change.to)}</code></div>
            </div>
          `)}
        </div>
        <div class="detail-block">
          <h3>Environment Changes (${envChanges.length})</h3>
          ${renderChangeList(envChanges, ([name, change]) => `
            <div class="change-item">
              <strong>${fmtText(name)}</strong>
              <div><code>${fmtText(change.from)}</code> -> <code>${fmtText(change.to)}</code></div>
            </div>
          `)}
        </div>
        <div class="detail-block">
          <h3>Snapshot Metadata</h3>
          <pre>${fmtJson(meta)}</pre>
        </div>
        ${diff.code_diff ? `
          <div class="detail-block">
            <h3>Working Tree Diff</h3>
            <pre>${fmtText(diff.code_diff)}</pre>
          </div>
        ` : ""}
      `;
    }

    async function loadOverview() {
      const overview = await fetchJson("/api/overview");
      renderCards(overview);
    }

    async function loadErrors() {
      const data = await fetchJson("/api/errors?limit=20");
      renderErrors(data.groups);
    }

    async function loadTraces() {
      const data = await fetchJson("/api/traces?limit=20");
      renderTraces(data.traces);
      if (!state.selectedTraceId && data.traces.length) {
        state.selectedTraceId = data.traces[0].trace_id;
        renderTraces(data.traces);
      }
    }

    async function loadSpans() {
      const data = await fetchJson("/api/spans?limit=20");
      renderSpans(data.spans);
    }

    async function loadSnapshots() {
      const data = await fetchJson("/api/snapshots?limit=20");
      renderSnapshots(data.snapshots);
      if (!state.selectedSnapshotId && data.snapshots.length) {
        state.selectedSnapshotId = data.snapshots[0].snapshot_id;
        renderSnapshots(data.snapshots);
      }
    }

    async function loadTraceDetail() {
      if (!state.selectedTraceId) {
        renderTraceDetail(null);
        return;
      }
      const trace = await fetchJson(`/api/traces/${encodeURIComponent(state.selectedTraceId)}`);
      renderTraceDetail(trace);
    }

    async function loadErrorExamples() {
      if (!state.selectedFingerprint) {
        renderErrorExamples([]);
        return;
      }
      const data = await fetchJson(`/api/errors/examples?fingerprint=${encodeURIComponent(state.selectedFingerprint)}`);
      renderErrorExamples(data.examples);
    }

    async function loadSnapshotDetail() {
      if (!state.selectedSnapshotId) {
        renderSnapshotDetail(null);
        return;
      }
      const snapshot = await fetchJson(`/api/snapshots/${encodeURIComponent(state.selectedSnapshotId)}`);
      renderSnapshotDetail(snapshot);
    }

    async function refreshAll() {
      try {
        await Promise.all([loadOverview(), loadErrors(), loadTraces(), loadSpans(), loadSnapshots()]);
        await Promise.all([loadTraceDetail(), loadErrorExamples(), loadSnapshotDetail()]);
        document.getElementById("last-refresh").textContent = `Last refresh ${new Date().toLocaleTimeString()}`;
      } catch (error) {
        document.getElementById("last-refresh").textContent = `Refresh failed: ${error.message}`;
      }
    }

    document.getElementById("refresh-btn").addEventListener("click", refreshAll);
    refreshAll();
    window.setInterval(refreshAll, 10000);
  </script>
</body>
</html>
"""


def _parse_int(value: str | None, default: int, *, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(parsed, maximum))


def _trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    http_meta = (trace.get("meta") or {}).get("http", {})
    return {
        **trace,
        "method": http_meta.get("method"),
        "path": http_meta.get("path"),
        "status_code": http_meta.get("status_code"),
    }


def _span_summary(span: dict[str, Any]) -> dict[str, Any]:
    meta = span.get("meta") or {}
    return {
        **span,
        "status_code": meta.get("http.status_code"),
        "rowcount": meta.get("rowcount"),
    }


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    meta = snapshot.get("meta") or {}
    dependencies = meta.get("dependencies") or {}
    env_vars = meta.get("env_vars") or {}
    return {
        **snapshot,
        "meta": meta,
        "git_sha": meta.get("git_sha"),
        "runtime": meta.get("runtime"),
        "dependency_count": len(dependencies),
        "env_var_count": len(env_vars),
    }


def _snapshot_detail(api: QueryAPI, snapshot_id: str) -> dict[str, Any] | None:
    snapshots = api.list_snapshots(limit=200)
    for idx, snapshot in enumerate(snapshots):
        if snapshot.get("snapshot_id") != snapshot_id:
            continue

        detail = _snapshot_summary(snapshot)
        previous_snapshot = snapshots[idx + 1] if idx + 1 < len(snapshots) else None
        if previous_snapshot is None:
            detail["previous"] = None
            detail["diff"] = {}
            return detail

        detail["previous"] = _snapshot_summary(previous_snapshot)
        detail["diff"] = api.diff_snapshots(
            previous_snapshot["snapshot_id"], snapshot["snapshot_id"]
        )
        return detail

    return None


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


def _overview(storage: Storage, api: QueryAPI) -> dict[str, Any]:
    counts_rows = storage.execute_sql(
        """
        SELECT
            count(*) AS events,
            sum(CASE WHEN event_type = 'trace' THEN 1 ELSE 0 END) AS traces,
            sum(CASE WHEN event_type = 'span' THEN 1 ELSE 0 END) AS spans,
            sum(CASE WHEN event_type = 'error' THEN 1 ELSE 0 END) AS errors,
            sum(CASE WHEN event_type = 'metric' THEN 1 ELSE 0 END) AS metrics,
            sum(CASE WHEN event_type = 'snapshot' THEN 1 ELSE 0 END) AS snapshots
        FROM events
        """
    )
    return {
        "counts": counts_rows[0] if counts_rows else {},
        "recent_errors": api.group_errors(limit=5),
        "recent_traces": [_trace_summary(t) for t in api.find_traces(limit=5)],
        "slow_spans": [_span_summary(s) for s in api.find_spans(limit=5)],
    }


def create_handler(storage: Storage) -> type[BaseHTTPRequestHandler]:
    api = QueryAPI(storage)

    class MonitorHandler(BaseHTTPRequestHandler):
        server_version = "AgentTraceMonitor/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/":
                self._respond_html(_INDEX_HTML)
                return

            if path == "/api/overview":
                self._respond_json(_overview(storage, api))
                return

            if path == "/api/errors":
                limit = _parse_int(query.get("limit", [None])[0], 20, minimum=1, maximum=200)
                since = query.get("since", [None])[0]
                route = query.get("path", [None])[0]
                self._respond_json(
                    {
                        "groups": api.group_errors(
                            group_by="fingerprint",
                            path=route,
                            since=since,
                            limit=limit,
                        )
                    }
                )
                return

            if path == "/api/errors/examples":
                fingerprint = query.get("fingerprint", [""])[0]
                limit = _parse_int(query.get("limit", [None])[0], 5, minimum=1, maximum=50)
                self._respond_json(
                    {"examples": api.get_error_examples(fingerprint, limit=limit)}
                )
                return

            if path == "/api/traces":
                limit = _parse_int(query.get("limit", [None])[0], 20, minimum=1, maximum=200)
                since = query.get("since", [None])[0]
                route = query.get("path", [None])[0]
                status = query.get("status", [None])[0]
                traces = api.find_traces(
                    path=route,
                    status=status,
                    since=since,
                    sort="timestamp",
                    desc=True,
                    limit=limit,
                )
                self._respond_json({"traces": [_trace_summary(t) for t in traces]})
                return

            if path.startswith("/api/traces/"):
                trace_id = path.rsplit("/", 1)[-1]
                trace = api.get_trace(trace_id)
                if trace is None:
                    self._respond_json({"error": f"Trace {trace_id} not found"}, status=404)
                    return
                trace["spans"] = [_span_summary(span) for span in trace.get("spans", [])]
                self._respond_json(_trace_summary(trace))
                return

            if path == "/api/spans":
                limit = _parse_int(query.get("limit", [None])[0], 20, minimum=1, maximum=200)
                since = query.get("since", [None])[0]
                kind = query.get("kind", [None])[0]
                trace_id = query.get("trace_id", [None])[0]
                spans = api.find_spans(
                    trace_id=trace_id,
                    kind=kind,
                    since=since,
                    sort="duration_ms",
                    desc=True,
                    limit=limit,
                )
                self._respond_json({"spans": [_span_summary(span) for span in spans]})
                return

            if path == "/api/snapshots":
                limit = _parse_int(query.get("limit", [None])[0], 20, minimum=1, maximum=200)
                snapshots = api.list_snapshots(limit=limit)
                self._respond_json(
                    {"snapshots": [_snapshot_summary(snapshot) for snapshot in snapshots]}
                )
                return

            if path.startswith("/api/snapshots/"):
                snapshot_id = path.rsplit("/", 1)[-1]
                snapshot = _snapshot_detail(api, snapshot_id)
                if snapshot is None:
                    self._respond_json(
                        {"error": f"Snapshot {snapshot_id} not found"}, status=404
                    )
                    return
                self._respond_json(snapshot)
                return

            self._respond_json({"error": f"Unknown path: {path}"}, status=404)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _respond_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _respond_json(self, payload: Any, *, status: int = 200) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return MonitorHandler


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m agenttrace.monitor",
        description="Run a local browser monitor for an agenttrace SQLite database.",
    )
    parser.add_argument("--db", default=".agenttrace.db", help="Path to the agenttrace database")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8787, help="Bind port")
    args = parser.parse_args(argv)

    storage = Storage(args.db)
    storage.initialize()

    server = ThreadingHTTPServer((args.host, args.port), create_handler(storage))
    print(f"AgentTrace monitor listening on http://{args.host}:{args.port}")
    print(f"Reading telemetry from {args.db}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        storage.close()


if __name__ == "__main__":
    main()
