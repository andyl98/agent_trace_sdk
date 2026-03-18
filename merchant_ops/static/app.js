const API = "";

function escHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

async function loadDashboard() {
  const mid = document.getElementById("merchant-id").value;
  const days = document.getElementById("days-range").value;
  const button = document.getElementById("btn-load-dashboard");
  const result = document.getElementById("dashboard-result");

  button.disabled = true;
  button.textContent = "Loading...";
  result.innerHTML = "";

  const start = performance.now();
  try {
    const response = await fetch(`${API}/api/dashboard/orders?merchant_id=${mid}&days=${days}`);
    const elapsedMs = performance.now() - start;
    const data = await response.json();
    const latencyClass = elapsedMs > 500 ? "latency-slow" : elapsedMs > 150 ? "latency-mid" : "latency-fast";

    if (!response.ok) {
      result.innerHTML = `<div class="alert alert-error">${escHtml(data.detail || "Request failed")}</div>`;
      return;
    }

    let html = `<span class="latency-badge ${latencyClass}">${elapsedMs.toFixed(0)}ms</span>`;
    html += '<table class="data-table"><thead><tr><th>Status</th><th>Count</th><th>Total</th></tr></thead><tbody>';
    for (const status of data.statuses || []) {
      html += `<tr><td>${escHtml(status.status)}</td><td>${status.count}</td><td>$${(status.total_cents / 100).toFixed(2)}</td></tr>`;
    }
    html += "</tbody></table>";
    html += `<p class="muted">${data.total_events} related order events</p>`;
    result.innerHTML = html;
  } catch (error) {
    result.innerHTML = `<div class="alert alert-error">${escHtml(error.message)}</div>`;
  } finally {
    button.disabled = false;
    button.textContent = "Load Dashboard";
  }
}

async function getQuote() {
  const button = document.getElementById("btn-get-quote");
  const result = document.getElementById("quote-result");
  button.disabled = true;
  button.textContent = "Loading...";

  const start = performance.now();
  try {
    const response = await fetch(`${API}/api/shipments/quote`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        origin_zip: document.getElementById("origin-zip").value,
        destination_zip: document.getElementById("dest-zip").value,
        weight_kg: parseFloat(document.getElementById("weight").value) || 5.0,
      }),
    });
    const elapsedMs = performance.now() - start;
    const latencyClass = elapsedMs > 500 ? "latency-slow" : elapsedMs > 150 ? "latency-mid" : "latency-fast";
    const text = await response.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = {detail: text};
    }

    if (response.ok) {
      result.innerHTML = `
        <div class="alert alert-success">
          <strong>${escHtml(data.carrier_name)}</strong> - $${(data.price_cents / 100).toFixed(2)} ${escHtml(data.currency)}
          <br><span class="muted">Est. ${data.estimated_days} days · Quote ${escHtml(data.quote_id)}</span>
        </div>
        <span class="latency-badge ${latencyClass}">${elapsedMs.toFixed(0)}ms</span>`;
      return;
    }

    result.innerHTML = `
      <div class="alert alert-error">${response.status}: ${escHtml(data.detail || JSON.stringify(data))}</div>
      <span class="latency-badge ${latencyClass}">${elapsedMs.toFixed(0)}ms</span>`;
  } catch (error) {
    result.innerHTML = `<div class="alert alert-error">${escHtml(error.message)}</div>`;
  } finally {
    button.disabled = false;
    button.textContent = "Get Quote";
  }
}

async function doLogin() {
  const button = document.getElementById("btn-login");
  const result = document.getElementById("login-result");
  button.disabled = true;
  button.textContent = "Loading...";

  try {
    const response = await fetch(`${API}/api/auth/login`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value,
      }),
    });

    if (response.ok) {
      const data = await response.json();
      result.innerHTML = `<div class="alert alert-success">Token issued (expires in ${data.expires_in}s)</div>`;
      return;
    }

    const text = await response.text();
    let detail;
    try {
      detail = JSON.parse(text).detail;
    } catch {
      detail = text;
    }
    result.innerHTML = `<div class="alert alert-error">${response.status}: ${escHtml(detail)}</div>`;
  } catch (error) {
    result.innerHTML = `<div class="alert alert-error">${escHtml(error.message)}</div>`;
  } finally {
    button.disabled = false;
    button.textContent = "Login";
  }
}
