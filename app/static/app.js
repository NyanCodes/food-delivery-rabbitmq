"use strict";

const POLL_INTERVAL_MS = 500;
const POLL_TIMEOUT_MS = 60_000;
const TERMINAL_STATES = new Set(["COMPLETED", "FAILED"]);
const form = document.querySelector("#order-form");
const formError = document.querySelector("#form-error");
const actionButtons = [...document.querySelectorAll(".actions button")];

const lanes = Object.fromEntries(
  [...document.querySelectorAll("[data-lane]")].map((card) => {
    const name = card.dataset.lane;
    return [name, {
      name,
      card,
      orderId: null,
      pollToken: 0,
      element(role) { return card.querySelector(`[data-role="${role}"]`); },
    }];
  }),
);

function readOrder() {
  const customerInput = document.querySelector("#customer");
  const restaurantInput = document.querySelector("#restaurant");
  const itemsInput = document.querySelector("#items");
  const items = itemsInput.value.split("\n").map((item) => item.trim()).filter(Boolean);
  customerInput.setCustomValidity(customerInput.value.trim() ? "" : "Enter a customer name.");
  restaurantInput.setCustomValidity(restaurantInput.value.trim() ? "" : "Enter a restaurant name.");
  itemsInput.setCustomValidity(items.length > 50 ? "Use no more than 50 items." : items.length ? "" : "Add at least one item.");
  formError.hidden = true;
  if (!form.reportValidity()) return null;
  return {
    customer: customerInput.value.trim(),
    restaurant: restaurantInput.value.trim(),
    items,
    total: Number(document.querySelector("#total").value),
  };
}

function setActionsBusy(busy) {
  for (const button of actionButtons) button.disabled = busy;
  form.setAttribute("aria-busy", String(busy));
}

function statusClass(status) {
  return String(status || "idle").toLowerCase().replaceAll("_", "-");
}

function setStatus(lane, status) {
  const badge = lane.element("status");
  badge.textContent = String(status).replaceAll("_", " ");
  badge.className = `status-badge ${statusClass(status)}`;
}

function setMessage(lane, message, isError = false) {
  const target = lane.element("message");
  target.textContent = message;
  target.classList.toggle("error", isError);
}

function resetLane(lane) {
  lane.pollToken += 1;
  lane.orderId = null;
  setStatus(lane, "PENDING");
  lane.element("api-time").textContent = "…";
  lane.element("round-trip").textContent = "…";
  lane.element("http-status").textContent = "…";
  lane.element("order-id").textContent = "Submitting…";
  lane.element("timeline").innerHTML = '<li class="empty-state">Waiting for the API…</li>';
  lane.element("raw").textContent = "Waiting for a response…";
  lane.element("refresh").hidden = true;
  setMessage(lane, lane.name === "async" ? "Publishing order.created…" : "Processing all steps inside the request…");
}

function formatDuration(value) {
  return Number.isFinite(Number(value)) ? `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })} ms` : "—";
}

function formatError(body, fallback) {
  if (!body) return fallback;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    return body.detail.map((item) => `${item.loc?.slice(1).join(".") || "request"}: ${item.msg}`).join("; ");
  }
  return fallback;
}

function renderTimeline(lane, events) {
  const timeline = lane.element("timeline");
  if (!events?.length) {
    timeline.innerHTML = '<li class="empty-state">No events recorded yet</li>';
    return;
  }
  timeline.replaceChildren(...events.map((event) => {
    const item = document.createElement("li");
    const title = document.createElement("div");
    title.className = "event-title";
    const stage = document.createElement("strong");
    stage.textContent = String(event.stage).replaceAll("_", " ");
    const timestamp = document.createElement("time");
    const date = new Date(event.at);
    timestamp.dateTime = event.at;
    timestamp.textContent = Number.isNaN(date.valueOf()) ? event.at : date.toLocaleTimeString();
    title.append(stage, timestamp);

    const meta = document.createElement("div");
    meta.className = "event-meta";
    if (event.worker) {
      const worker = document.createElement("span");
      worker.className = "event-worker";
      worker.textContent = event.worker;
      meta.append(worker);
    }
    if (event.detail) meta.append(document.createTextNode(`${event.worker ? " · " : ""}${event.detail}`));
    item.append(title, meta);
    return item;
  }));
}

function renderOrder(lane, order) {
  setStatus(lane, order.status);
  lane.element("order-id").textContent = order.id || lane.orderId;
  lane.element("raw").textContent = JSON.stringify(order, null, 2);
  renderTimeline(lane, order.timeline);
  if (order.status === "COMPLETED") setMessage(lane, "Order journey completed successfully.");
  else if (order.status === "FAILED") setMessage(lane, "Order processing failed. Inspect the timeline for the responsible worker.", true);
  else setMessage(lane, "Workers are processing this order. Timeline updates automatically.");
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  let body = null;
  try { body = await response.json(); } catch { body = null; }
  return { response, body };
}

const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

async function trackOrder(lane, orderId) {
  const token = ++lane.pollToken;
  const deadline = performance.now() + POLL_TIMEOUT_MS;
  lane.element("refresh").hidden = true;

  while (token === lane.pollToken && performance.now() < deadline) {
    try {
      const { response, body } = await requestJson(`/orders/${encodeURIComponent(orderId)}`);
      if (!response.ok || !body) {
        setMessage(lane, formatError(body, `Tracking failed with HTTP ${response.status}.`), true);
      } else {
        renderOrder(lane, body);
        if (TERMINAL_STATES.has(body.status)) {
          refreshStats();
          return;
        }
      }
    } catch (error) {
      setMessage(lane, `Tracking connection lost: ${error.message}. Retrying…`, true);
    }
    await wait(POLL_INTERVAL_MS);
  }

  if (token === lane.pollToken) {
    setMessage(lane, "Live tracking paused after 60 seconds. The order may still be processing.", true);
    lane.element("refresh").hidden = false;
  }
}

async function submitOrder(laneName, order) {
  const lane = lanes[laneName];
  const endpoint = laneName === "async" ? "/orders" : "/orders/sync";
  resetLane(lane);
  const started = performance.now();

  try {
    const { response, body } = await requestJson(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(order),
    });
    const roundTrip = performance.now() - started;
    lane.element("round-trip").textContent = formatDuration(roundTrip);
    lane.element("http-status").textContent = String(response.status);
    lane.element("raw").textContent = JSON.stringify(body ?? { error: "Response was not JSON" }, null, 2);

    if (!response.ok || !body) {
      setStatus(lane, "ERROR");
      lane.element("api-time").textContent = "—";
      lane.element("order-id").textContent = "Not created";
      setMessage(lane, formatError(body, `Request failed with HTTP ${response.status}.`), true);
      return;
    }

    lane.orderId = body.order_id;
    lane.element("order-id").textContent = body.order_id;
    lane.element("api-time").textContent = formatDuration(body.api_time_ms);
    setStatus(lane, body.status);
    setMessage(lane, laneName === "async" ? "Accepted. Waiting for background workers…" : "Request completed. Loading its event timeline…");
    refreshStats();
    void trackOrder(lane, body.order_id);
  } catch (error) {
    lane.element("round-trip").textContent = formatDuration(performance.now() - started);
    lane.element("http-status").textContent = "Network";
    lane.element("api-time").textContent = "—";
    lane.element("order-id").textContent = "Not created";
    lane.element("raw").textContent = String(error);
    setStatus(lane, "ERROR");
    setMessage(lane, `Could not reach the API: ${error.message}`, true);
  }
}

async function run(mode) {
  const order = readOrder();
  if (!order) return;
  setActionsBusy(true);
  try {
    if (mode === "compare") {
      await Promise.allSettled([submitOrder("async", order), submitOrder("sync", order)]);
    } else {
      await submitOrder(mode, order);
    }
  } finally {
    setActionsBusy(false);
  }
}

async function refreshHealth() {
  try {
    const { response, body } = await requestJson("/health");
    for (const service of ["broker", "database"]) {
      const ok = response.ok && Boolean(body?.[service]);
      document.querySelector(`#${service}-health`).textContent = ok ? "Online" : "Offline";
      document.querySelector(`#${service}-dot`).className = `dot ${ok ? "ok" : "down"}`;
    }
  } catch {
    for (const service of ["broker", "database"]) {
      document.querySelector(`#${service}-health`).textContent = "Unavailable";
      document.querySelector(`#${service}-dot`).className = "dot down";
    }
  }
}

async function refreshStats() {
  try {
    const { response, body } = await requestJson("/stats");
    if (!response.ok || !body) return;
    const values = {
      pending: body.PENDING || 0,
      processing: body.PROCESSING || 0,
      ready: body.READY || 0,
      confirmed: body.CONFIRMED || 0,
      completed: body.COMPLETED || 0,
      failed: body.FAILED || 0,
    };
    for (const [name, value] of Object.entries(values)) document.querySelector(`#stat-${name}`).textContent = value;
  } catch {
    // Keep the most recently known counts when the API is temporarily unavailable.
  }
}

document.querySelector("#async-button").addEventListener("click", () => run("async"));
document.querySelector("#sync-button").addEventListener("click", () => run("sync"));
document.querySelector("#compare-button").addEventListener("click", () => run("compare"));
form.addEventListener("submit", (event) => { event.preventDefault(); run("compare"); });
document.querySelector("#items").addEventListener("input", (event) => event.currentTarget.setCustomValidity(""));
document.querySelector("#customer").addEventListener("input", (event) => event.currentTarget.setCustomValidity(""));
document.querySelector("#restaurant").addEventListener("input", (event) => event.currentTarget.setCustomValidity(""));
for (const lane of Object.values(lanes)) {
  lane.element("refresh").addEventListener("click", () => {
    if (lane.orderId) void trackOrder(lane, lane.orderId);
  });
}

refreshHealth();
refreshStats();
window.setInterval(refreshHealth, 10_000);
window.setInterval(refreshStats, 5_000);
