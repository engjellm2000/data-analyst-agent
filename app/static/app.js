const $ = (selector) => document.querySelector(selector);
const windowSelect = $("#window-select");
const runButton = $("#run-button");
const statusMessage = $("#status-message");
let appConfig = { auth_enabled: false };
let accessToken = sessionStorage.getItem("biAgentAccessToken");
let activeTenant = sessionStorage.getItem("biAgentTenantId");
let selectedCurrency = "USD";
let currentInvestigation = null;
let activeInvestigationRequest = null;
const DEFAULT_ALERT_THRESHOLDS = { revenue: 10, returns: 3, delivery: 1 };

function currency(value, compact = false) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: selectedCurrency,
    maximumFractionDigits: compact ? 0 : 2,
    notation: compact && Math.abs(value) >= 10000 ? "compact" : "standard",
  }).format(value);
}

function percentChange(current, previous) {
  if (!previous) return "No prior baseline";
  const delta = ((current - previous) / previous) * 100;
  return `${delta > 0 ? "+" : ""}${delta.toFixed(1)}% vs prior window`;
}

function changeClass(element, current, previous, invert = false) {
  const delta = current - previous;
  element.classList.remove("negative", "positive");
  if (delta === 0) return;
  const isPositive = invert ? delta < 0 : delta > 0;
  element.classList.add(isPositive ? "positive" : "negative");
}

function dateLabel(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${value}T00:00:00Z`));
}

function renderMetric(id, current, previous, formatter, invert = false) {
  const value = $(`#metric-${id}`);
  const change = $(`#change-${id}`);
  if (current === null || previous === null) {
    value.textContent = current === null ? "Not available" : formatter(current);
    change.textContent = "Unavailable in this dataset";
    change.classList.remove("negative", "positive");
    return;
  }
  value.textContent = formatter(current);
  change.textContent = percentChange(current, previous);
  changeClass(change, current, previous, invert);
}

function renderChart(series) {
  const svg = $("#revenue-chart");
  if (!series.length) {
    svg.innerHTML = "";
    svg.setAttribute("aria-label", "No daily revenue values are available for this period.");
    return;
  }
  const width = 760;
  const height = 194;
  const pad = { top: 13, right: 12, bottom: 18, left: 54 };
  const values = series.map((item) => item.revenue);
  const maximum = Math.max(...values) * 1.08 || 1;
  const minimum = 0;
  const chartHeight = height - pad.top - pad.bottom;
  const chartWidth = width - pad.left - pad.right;
  const points = series.map((item, index) => {
    const x = pad.left + (series.length === 1 ? chartWidth / 2 : (index / (series.length - 1)) * chartWidth);
    const y = pad.top + chartHeight - ((item.revenue - minimum) / (maximum - minimum)) * chartHeight;
    return { x, y };
  });
  const path = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const areaPath = `${path} L${points.at(-1).x.toFixed(2)},${(pad.top + chartHeight).toFixed(2)} L${pad.left},${(pad.top + chartHeight).toFixed(2)} Z`;
  const ticks = [0, 0.5, 1].map((fraction) => {
    const y = pad.top + chartHeight * fraction;
    const amount = maximum * (1 - fraction);
    return `<line class="chart-grid" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"></line>
      <text class="chart-label" x="${pad.left - 9}" y="${y + 3}" text-anchor="end">${currency(amount, true)}</text>`;
  }).join("");
  const markers = [0, Math.floor((points.length - 1) / 2), points.length - 1]
    .filter((index, order, all) => all.indexOf(index) === order)
    .map((index) => `<circle class="chart-point" cx="${points[index].x}" cy="${points[index].y}" r="3.1"><title>${dateLabel(series[index].date)}: ${currency(series[index].revenue)}</title></circle>`)
    .join("");
  svg.innerHTML = `${ticks}<path class="chart-area" d="${areaPath}"></path><path class="chart-path" d="${path}"></path>${markers}`;
  svg.setAttribute("aria-label", `Daily net revenue from ${dateLabel(series[0].date)} to ${dateLabel(series.at(-1).date)}. ${series.length} daily values.`);
  $("#chart-start").textContent = dateLabel(series[0].date);
  $("#chart-end").textContent = dateLabel(series.at(-1).date);
}

function renderForecast(forecast) {
  const svg = $("#forecast-chart");
  if (!forecast?.available) {
    $("#forecast-total").textContent = "Unavailable";
    $("#forecast-range").textContent = forecast?.reason
      || (forecast ? "Run an investigation to calculate a planning estimate." : "This saved report predates the forecast feature; rerun it to add a projection.");
    $("#forecast-description").textContent = forecast
      ? "More observed history is needed before a forecast can be shown."
      : "This saved run does not include a forecast.";
    $("#forecast-method").textContent = forecast
      ? "A forecast is omitted rather than filling missing source metrics with zero."
      : "Rerun the same comparison window to calculate a projection.";
    svg.replaceChildren();
    svg.setAttribute("aria-label", forecast?.reason || "Revenue forecast unavailable.");
    return;
  }

  $("#forecast-total").textContent = currency(forecast.projected_total, true);
  $("#forecast-range").textContent = `Approximate planning range ${currency(forecast.lower_total, true)}–${currency(forecast.upper_total, true)} · trailing-window comparison ${forecast.change_vs_baseline_pct === null ? "unavailable" : `${forecast.change_vs_baseline_pct > 0 ? "+" : ""}${forecast.change_vs_baseline_pct}%`}`;
  $("#forecast-description").textContent = `${forecast.lookback_days} observed calendar days projected ${forecast.horizon_days} days forward.`;
  $("#forecast-horizon").textContent = `${forecast.horizon_days}-day horizon`;
  $("#forecast-method").textContent = `${forecast.method} Planning range is approximate, not a confidence guarantee.`;

  const points = [...forecast.history, ...forecast.daily];
  const width = 760;
  const height = 150;
  const pad = { top: 10, right: 12, bottom: 20, left: 12 };
  const maximum = Math.max(...points.map((point) => point.upper ?? point.revenue), 1) * 1.08;
  const chartWidth = width - pad.left - pad.right;
  const chartHeight = height - pad.top - pad.bottom;
  const pointAt = (point, index) => ({
    x: pad.left + (index / Math.max(points.length - 1, 1)) * chartWidth,
    y: pad.top + chartHeight - (point.revenue / maximum) * chartHeight,
  });
  const historyPoints = forecast.history.map(pointAt);
  const forecastPoints = forecast.daily.map((point, index) => pointAt(point, forecast.history.length + index));
  const upperPoints = forecast.daily.map((point, index) => pointAt({ revenue: point.upper }, forecast.history.length + index));
  const lowerPoints = forecast.daily.map((point, index) => pointAt({ revenue: point.lower }, forecast.history.length + index));
  const pathFor = (items) => items.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const historyPath = pathFor(historyPoints);
  const forecastPath = `M${historyPoints.at(-1).x.toFixed(2)},${historyPoints.at(-1).y.toFixed(2)} ${pathFor(forecastPoints).replace(/^M/, "L")}`;
  const bandPath = `${pathFor(upperPoints)} ${lowerPoints.slice().reverse().map((point) => `L${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ")} Z`;
  const baseY = (height - pad.bottom).toFixed(2);
  const start = historyPoints[0];
  const join = historyPoints.at(-1);
  const end = forecastPoints.at(-1);
  svg.innerHTML = `
    <line class="forecast-grid" x1="${pad.left}" y1="${pad.top + chartHeight / 2}" x2="${width - pad.right}" y2="${pad.top + chartHeight / 2}"></line>
    <line class="forecast-grid" x1="${pad.left}" y1="${baseY}" x2="${width - pad.right}" y2="${baseY}"></line>
    <path class="forecast-band" d="${bandPath}"></path>
    <path class="forecast-history-path" d="${historyPath}"></path>
    <path class="forecast-path" d="${forecastPath}"></path>
    <line class="forecast-divider" x1="${join.x.toFixed(2)}" y1="${pad.top}" x2="${join.x.toFixed(2)}" y2="${baseY}"></line>
    <text class="forecast-label" x="${start.x}" y="${height - 2}">${dateLabel(forecast.history[0].date)}</text>
    <text class="forecast-label" x="${join.x}" y="${height - 2}" text-anchor="middle">${dateLabel(forecast.history.at(-1).date)}</text>
    <text class="forecast-label" x="${end.x}" y="${height - 2}" text-anchor="end">${dateLabel(forecast.daily.at(-1).date)}</text>
  `;
  svg.setAttribute("aria-label", `Revenue history through ${dateLabel(forecast.history.at(-1).date)} and a ${forecast.horizon_days}-day trend projection through ${dateLabel(forecast.daily.at(-1).date)} with an approximate planning range.`);
}

function alertThresholds() {
  const values = {
    revenue: Number($("#alert-revenue-threshold").value),
    returns: Number($("#alert-returns-threshold").value),
    delivery: Number($("#alert-delivery-threshold").value),
  };
  return {
    revenue: Number.isFinite(values.revenue) ? Math.min(90, Math.max(1, values.revenue)) : DEFAULT_ALERT_THRESHOLDS.revenue,
    returns: Number.isFinite(values.returns) ? Math.min(50, Math.max(0.1, values.returns)) : DEFAULT_ALERT_THRESHOLDS.returns,
    delivery: Number.isFinite(values.delivery) ? Math.min(60, Math.max(0.1, values.delivery)) : DEFAULT_ALERT_THRESHOLDS.delivery,
  };
}

function renderAlerts(result) {
  const current = result.metrics.current;
  const previous = result.metrics.previous;
  const thresholds = alertThresholds();
  const rules = [
    {
      label: "Net revenue",
      comparison: current.revenue !== null && previous.revenue > 0
        ? `${currency(previous.revenue, true)} → ${currency(current.revenue, true)}`
        : "No comparable baseline",
      triggered: previous.revenue > 0 && ((previous.revenue - current.revenue) / previous.revenue) * 100 >= thresholds.revenue,
      unavailable: previous.revenue <= 0 || current.revenue === null,
      detail: `Decline of at least ${thresholds.revenue}%`,
    },
    {
      label: "Return rate",
      comparison: current.return_rate !== null && previous.return_rate !== null
        ? `${(previous.return_rate * 100).toFixed(1)}% → ${(current.return_rate * 100).toFixed(1)}%`
        : "Not captured in this dataset",
      triggered: current.return_rate !== null && previous.return_rate !== null
        && (current.return_rate - previous.return_rate) * 100 >= thresholds.returns,
      unavailable: current.return_rate === null || previous.return_rate === null,
      detail: `Increase of at least ${thresholds.returns} pp`,
    },
    {
      label: "Delivery time",
      comparison: current.delivery_days !== null && previous.delivery_days !== null
        ? `${previous.delivery_days.toFixed(1)} → ${current.delivery_days.toFixed(1)} days`
        : "Not captured in this dataset",
      triggered: current.delivery_days !== null && previous.delivery_days !== null
        && current.delivery_days - previous.delivery_days >= thresholds.delivery,
      unavailable: current.delivery_days === null || previous.delivery_days === null,
      detail: `Increase of at least ${thresholds.delivery} day${thresholds.delivery === 1 ? "" : "s"}`,
    },
  ];
  $("#alerts-list").innerHTML = rules.map((rule) => {
    const state = rule.unavailable ? "Unavailable" : rule.triggered ? "Triggered" : "Clear";
    const stateClass = rule.unavailable ? "unavailable" : rule.triggered ? "triggered" : "clear";
    return `<article class="alert-row ${stateClass}">
      <span class="alert-state">${state}</span>
      <strong>${escapeHtml(rule.label)}</strong>
      <span>${escapeHtml(rule.comparison)}</span>
      <span class="alert-rule">${escapeHtml(rule.detail)}</span>
    </article>`;
  }).join("");
}

function renderFindings(findings) {
  $("#finding-count").textContent = `${findings.length} ${findings.length === 1 ? "finding" : "findings"}`;
  $("#findings").innerHTML = findings.map((finding) => {
    const evidence = finding.evidence.map((item) =>
      `<li><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong></li>`,
    ).join("");
    return `<article class="finding" data-priority="${escapeHtml(finding.priority)}">
      <div class="finding-summary">
        <div class="finding-topline"><span class="priority-mark" aria-hidden="true"></span><span class="priority-label">${escapeHtml(finding.priority)} priority</span></div>
        <h3>${escapeHtml(finding.title)}</h3>
        <p>${escapeHtml(finding.summary)}</p>
      </div>
      <div class="finding-detail">
        <div class="route-column">
          <div class="route-label">Measured evidence</div>
          <ul class="evidence-list">${evidence}</ul>
          <p class="finding-explanation">${escapeHtml(finding.explanation)}</p>
        </div>
        <div class="route-column">
          <div class="route-label">Next test</div>
          <p class="recommendation">${escapeHtml(finding.recommendation)}</p>
        </div>
      </div>
    </article>`;
  }).join("");
}

function renderTrace(traces) {
  const entries = Object.entries(traces || {}).flatMap(([findingId, trace]) =>
    (trace.trace || []).map((item) => ({ findingId, ...item })));
  if (!entries.length) {
    $("#trace-feed").innerHTML = '<p class="muted">No trace is available.</p>';
    return;
  }
  $("#trace-feed").innerHTML = entries.map((entry) => `<article class="trace-entry">
    <span class="trace-status ${escapeHtml(entry.status)}">${escapeHtml(entry.status)}</span>
    <div><strong>${escapeHtml(entry.step)}</strong><p>${escapeHtml(entry.detail)}</p>${entry.hypothesis ? `<code>${escapeHtml(entry.hypothesis)}</code>` : ""}</div>
    <span class="trace-id">${escapeHtml(entry.findingId)}</span>
  </article>`).join("");
}

function renderEval(result) {
  const benchmark = result.fixture_benchmark;
  if (!benchmark) {
    $("#eval-scoreboard").innerHTML = '<span>No measured fixture result is available.</span>';
    return;
  }
  const fields = [["Detection", benchmark.detection_rate], ["Segment match", benchmark.root_cause_accuracy], ["False alarms", benchmark.false_alarm_rate], ["Compute cost / run", currency(benchmark.cost_per_investigation_usd)]];
  $("#eval-scoreboard").innerHTML = fields.map(([label, value]) => `<div><span>${label}</span><strong>${typeof value === "number" && label !== "Compute cost / run" ? `${(value * 100).toFixed(0)}%` : value}</strong></div>`).join("");
}

function renderRevenueDrivers(groups) {
  const renderGroup = (label, drivers) => {
    if (!drivers.length) {
      return `<section class="driver-group" aria-label="${label} revenue movements"><h3>${label}</h3><p class="muted">Not captured in this dataset.</p></section>`;
    }
    const selected = [...drivers]
      .sort((left, right) => Math.abs(right.change) - Math.abs(left.change))
      .slice(0, 3);
    const rows = selected.map((driver) => {
      const direction = driver.change > 0 ? "+" : "";
      const percentage = driver.change_pct === null ? "No prior baseline" : `${direction}${(driver.change_pct * 100).toFixed(1)}%`;
      return `<li><span>${escapeHtml(driver.segment)}</span><strong class="${driver.change < 0 ? "down" : "up"}">${direction}${currency(driver.change, true)} <em>${percentage}</em></strong></li>`;
    }).join("");
    return `<section class="driver-group" aria-label="${label} revenue movements"><h3>${label}</h3><ul>${rows}</ul></section>`;
  };
  $("#revenue-drivers").innerHTML = renderGroup("By category", groups.category) + renderGroup("By channel", groups.channel);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function renderInvestigation(result) {
  currentInvestigation = result;
  $("#export-json-button").disabled = false;
  $("#export-csv-button").disabled = false;
  const current = result.metrics.current;
  const previous = result.metrics.previous;
  renderMetric("revenue", current.revenue, previous.revenue, (value) => currency(value, true));
  renderMetric("aov", current.aov, previous.aov, (value) => currency(value));
  renderMetric("returns", current.return_rate, previous.return_rate, (value) => `${(value * 100).toFixed(1)}%`, true);
  renderMetric("delivery", current.delivery_days, previous.delivery_days, (value) => `${value.toFixed(1)} days`, true);
  $("#current-dates").textContent = `${dateLabel(result.current_start)} — ${dateLabel(result.current_end)}`;
  $("#previous-dates").textContent = `${dateLabel(result.previous_start)} — ${dateLabel(result.previous_end)}`;
  $("#scope-orders").textContent = `${current.orders.toLocaleString("en-US")} current · ${previous.orders.toLocaleString("en-US")} prior`;
  $("#order-count").textContent = `${current.orders.toLocaleString("en-US")} orders`;
  $("#chart-period").textContent = `Daily net revenue · ${dateLabel(result.current_start)} to ${dateLabel(result.current_end)}`;
  $("#chart-currency").textContent = `Daily net revenue · ${selectedCurrency}`;
  $("#comparison-copy").textContent = `${result.method.comparison} Findings are ranked by priority and linked to segment measurements.`;
  renderChart(result.series);
  renderForecast(result.forecast);
  renderAlerts(result);
  renderRevenueDrivers(result.revenue_drivers);
  renderFindings(result.findings);
  renderTrace(result.investigation_traces);
  $("#thresholds").innerHTML = Object.entries(result.method.thresholds)
    .map(([name, value]) => `<span><strong>${escapeHtml(name.replaceAll("_", " "))}:</strong> ${escapeHtml(value)}</span>`)
    .join("");
}

function clearInvestigation() {
  currentInvestigation = null;
  $("#export-json-button").disabled = true;
  $("#export-csv-button").disabled = true;
  for (const id of ["revenue", "aov", "returns", "delivery"]) {
    $(`#metric-${id}`).textContent = "—";
    $(`#change-${id}`).textContent = "No data available";
    $(`#change-${id}`).classList.remove("negative", "positive");
  }
  $("#current-dates").textContent = "—";
  $("#previous-dates").textContent = "—";
  $("#scope-orders").textContent = "—";
  $("#order-count").textContent = "— orders";
  $("#revenue-chart").replaceChildren();
  $("#revenue-drivers").replaceChildren();
  $("#findings").innerHTML = '<p class="muted">No report is available yet. Load a data source, then run an investigation.</p>';
  $("#finding-count").textContent = "0 findings";
  $("#trace-feed").innerHTML = '<p class="muted">Run an investigation to view its trace.</p>';
  $("#alerts-list").innerHTML = '<p class="muted">No report is available to evaluate.</p>';
  renderForecast(null);
}

async function requestJson(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (activeTenant) headers.set("X-Tenant-ID", activeTenant);
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      // Keep the HTTP status as the actionable fallback for non-JSON errors.
    }
    throw new Error(detail);
  }
  return response.json();
}

async function runInvestigation(showStatus = true, refreshHistory = true) {
  activeInvestigationRequest?.abort();
  const controller = new AbortController();
  activeInvestigationRequest = controller;
  runButton.disabled = true;
  runButton.querySelector("span:last-child").textContent = "Investigating…";
  statusMessage.classList.remove("error");
  statusMessage.textContent = showStatus ? "Comparing periods and checking segment evidence…" : "";
  try {
    const result = await requestJson("/api/investigations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ window_days: Number(windowSelect.value) }),
      signal: controller.signal,
    });
    if (activeInvestigationRequest !== controller) return;
    renderInvestigation(result);
    statusMessage.textContent = showStatus
      ? `Investigation complete · ${new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(result.run_at))}`
      : "";
    if (refreshHistory) await loadHistory();
  } catch (error) {
    if (error.name === "AbortError" || activeInvestigationRequest !== controller) return;
    statusMessage.classList.add("error");
    statusMessage.textContent = `Could not run investigation: ${error.message}. Check that the local app is running and try again.`;
  } finally {
    if (activeInvestigationRequest !== controller) return;
    activeInvestigationRequest = null;
    runButton.disabled = false;
    runButton.querySelector("span:last-child").textContent = "Run investigation";
  }
}

async function loadDashboard() {
  const main = document.querySelector("main");
  main.hidden = true;
  clearInvestigation();
  try {
    const data = await requestJson(`/api/dashboard?window_days=${Number(windowSelect.value)}`);
    main.hidden = false;
    selectedCurrency = data.dataset.currency || "USD";
    $("#dataset-summary").textContent = `${data.dataset.label} · ${data.dataset.orders.toLocaleString("en-US")} orders`;
    $("#dataset-range").textContent = `${dateLabel(data.dataset.start_date)} – ${dateLabel(data.dataset.end_date)}`;
    $("#dataset-source-label").textContent = data.dataset.source || "Source unavailable";
    $("#dataset-scope-title").textContent = data.dataset.source_url
      ? "Public static dataset"
      : appConfig.auth_enabled ? "Shopify workspace data" : "Synthetic demo data";
    $("#dataset-scope-description").textContent = data.dataset.source_url
      ? "Imported snapshot; not a live store connection."
      : appConfig.auth_enabled
        ? "Tenant-isolated snapshot from Shopify; only selected order fields are stored."
        : "Generated locally; not real customer data.";
    const limitations = [...(data.dataset.limitations || [])];
    const quality = data.dataset.quality || {};
    if (quality.delivered_orders_missing_items) {
      limitations.push(`${quality.delivered_orders_missing_items} delivered orders without items were excluded.`);
    }
    if (quality.delivered_orders_missing_purchase_date) {
      limitations.push(`${quality.delivered_orders_missing_purchase_date} delivered orders without purchase dates were excluded.`);
    }
    if (quality.included_orders_missing_delivery_date) {
      limitations.push(`${quality.included_orders_missing_delivery_date} included orders have no delivery timestamp.`);
    }
    if (quality.included_orders_missing_category) {
      limitations.push(`${quality.included_orders_missing_category} included orders have no mapped category.`);
    }
    if (quality.included_orders_missing_customer_region) {
      limitations.push(`${quality.included_orders_missing_customer_region} included orders have no customer region.`);
    }
    $("#dataset-limitations").hidden = limitations.length === 0;
    $("#dataset-limitations").textContent = limitations.length
      ? `Dataset notes: ${limitations.join(" ")}`
      : "";
    if (data.investigation) {
      renderInvestigation(data.investigation);
      statusMessage.textContent = "Showing the last saved investigation for this window.";
    } else if (data.dataset.orders > 0) {
      await runInvestigation(false, false);
    } else {
      clearInvestigation();
      statusMessage.textContent = appConfig.auth_enabled
        ? "Connect Shopify and sync recent orders to begin."
        : "No dataset is available yet.";
    }
    await loadHistory();
  } catch (error) {
    statusMessage.classList.add("error");
    statusMessage.textContent = `Could not load the local dataset: ${error.message}. Restart the app and try again.`;
    $("#dataset-summary").textContent = "Dataset unavailable";
    if (appConfig.auth_enabled) setAccessStatus(`Could not load workspace data: ${error.message}`, true);
    else main.hidden = false;
  }
}

async function loadEvals() {
  try { renderEval(await requestJson("/api/evals")); }
  catch { $("#eval-scoreboard").innerHTML = '<span>Benchmark unavailable.</span>'; }
}

async function loadHistory() {
  const select = $("#history-select");
  try {
    const result = await requestJson("/api/investigations?limit=30");
    select.replaceChildren();
    for (const item of result.investigations) {
      const option = document.createElement("option");
      option.value = item.investigation_id;
      const runDate = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" })
        .format(new Date(item.run_at));
      const findingLabel = `${item.finding_count} ${item.finding_count === 1 ? "finding" : "findings"}`;
      option.textContent = `${runDate} · ${item.window_days} days · ${findingLabel}`;
      select.append(option);
    }
    if (!result.investigations.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No saved investigations";
      select.append(option);
    }
  } catch (error) {
    select.replaceChildren();
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "History unavailable";
    select.append(option);
    statusMessage.classList.add("error");
    statusMessage.textContent = `Could not load saved investigations: ${error.message}`;
  }
}

function restoreAlertThresholds() {
  const key = `biAgentAlertThresholds:${activeTenant || "local"}`;
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(key) || "{}");
  } catch (error) {
    saved = {};
    statusMessage.classList.add("error");
    statusMessage.textContent = `Could not read saved alert rules: ${error.message}. Default thresholds are in use.`;
  }
  if (!saved || typeof saved !== "object" || Array.isArray(saved)) saved = {};
  const values = {
    revenue: Number.isFinite(Number(saved.revenue)) ? Number(saved.revenue) : DEFAULT_ALERT_THRESHOLDS.revenue,
    returns: Number.isFinite(Number(saved.returns)) ? Number(saved.returns) : DEFAULT_ALERT_THRESHOLDS.returns,
    delivery: Number.isFinite(Number(saved.delivery)) ? Number(saved.delivery) : DEFAULT_ALERT_THRESHOLDS.delivery,
  };
  $("#alert-revenue-threshold").value = String(Math.min(90, Math.max(1, values.revenue)));
  $("#alert-returns-threshold").value = String(Math.min(50, Math.max(0.1, values.returns)));
  $("#alert-delivery-threshold").value = String(Math.min(60, Math.max(0.1, values.delivery)));
  if (currentInvestigation) renderAlerts(currentInvestigation);
}

function saveAlertThresholds() {
  const values = alertThresholds();
  $("#alert-revenue-threshold").value = String(values.revenue);
  $("#alert-returns-threshold").value = String(values.returns);
  $("#alert-delivery-threshold").value = String(values.delivery);
  const key = `biAgentAlertThresholds:${activeTenant || "local"}`;
  try {
    localStorage.setItem(key, JSON.stringify(values));
  } catch {
    statusMessage.textContent = "Alert rules changed for this session, but could not be saved in this browser.";
  }
  if (currentInvestigation) renderAlerts(currentInvestigation);
}

async function openSavedInvestigation() {
  const investigationId = $("#history-select").value;
  if (!investigationId) return;
  const button = $("#load-history-button");
  button.disabled = true;
  try {
    const result = await requestJson(`/api/investigations/${encodeURIComponent(investigationId)}`);
    windowSelect.value = String(result.window_days);
    renderInvestigation(result);
    statusMessage.classList.remove("error");
    statusMessage.textContent = `Opened saved investigation · ${dateLabel(result.current_start)} to ${dateLabel(result.current_end)}.`;
  } catch (error) {
    statusMessage.classList.add("error");
    statusMessage.textContent = `Could not open saved investigation: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function downloadFile(contents, mimeType, extension) {
  if (!currentInvestigation) return;
  const blob = new Blob([contents], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const reportId = String(currentInvestigation.investigation_id || "report").replace(/[^a-zA-Z0-9-]/g, "");
  anchor.download = `investigation-${currentInvestigation.current_end || "report"}-${reportId.slice(0, 8)}.${extension}`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function exportJson() {
  if (!currentInvestigation) return;
  downloadFile(JSON.stringify(currentInvestigation, null, 2), "application/json;charset=utf-8", "json");
}

function exportCsv() {
  if (!currentInvestigation) return;
  const result = currentInvestigation;
  const rows = [["section", "item", "current", "previous", "details"]];
  for (const metric of ["revenue", "aov", "orders", "return_rate", "delivery_days"]) {
    rows.push(["metric", metric, result.metrics.current[metric], result.metrics.previous[metric], `${result.current_start} to ${result.current_end}`]);
  }
  for (const finding of result.findings) {
    rows.push(["finding", finding.title, finding.priority, finding.segment, `${finding.summary} ${finding.explanation} Next test: ${finding.recommendation}`]);
    for (const evidence of finding.evidence) {
      rows.push(["evidence", `${finding.title}: ${evidence.label}`, evidence.value, "", finding.explanation]);
    }
  }
  for (const point of result.series || []) {
    rows.push(["daily_revenue", point.date, point.revenue, "", `${point.orders} orders`]);
  }
  for (const [dimension, drivers] of Object.entries(result.revenue_drivers || {})) {
    for (const driver of drivers) {
      const changeRate = driver.change_pct === null ? "unavailable" : `${(driver.change_pct * 100).toFixed(1)}%`;
      rows.push(["segment_movement", `${dimension}: ${driver.segment}`, driver.current_revenue, driver.previous_revenue, `Change ${driver.change} (${changeRate})`]);
    }
  }
  for (const anomaly of result.anomalies || []) {
    rows.push(["anomaly", anomaly.date, anomaly.value, anomaly.robust_z, `${anomaly.metric} · ${anomaly.direction}; baseline median ${anomaly.baseline_median}`]);
  }
  for (const [findingId, trace] of Object.entries(result.investigation_traces || {})) {
    for (const item of trace.trace || []) {
      rows.push(["investigation_trace", `${findingId}: ${item.step}`, item.status, item.hypothesis || "", item.detail]);
    }
  }
  if (result.forecast?.available) {
    rows.push(["forecast", "projected_total", result.forecast.projected_total, "", result.forecast.method]);
    for (const point of result.forecast.daily) {
      rows.push(["forecast_day", point.date, point.revenue, `${point.lower}–${point.upper}`, "Approximate planning range"]);
    }
  }
  const csv = rows.map((row) => row.map((cell) => {
    let value = cell === null || cell === undefined ? "" : String(cell);
    if (typeof cell === "string" && /^[\t\r\n ]*[=+\-@]/.test(value)) value = `'${value}`;
    return `"${value.replace(/"/g, '""')}"`;
  }).join(",")).join("\r\n");
  downloadFile(`\uFEFF${csv}`, "text/csv;charset=utf-8", "csv");
}

$("#method-toggle").addEventListener("click", (event) => {
  const button = event.currentTarget;
  const panel = $("#method-panel");
  const isExpanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!isExpanded));
  panel.hidden = isExpanded;
  button.lastElementChild.textContent = isExpanded ? "＋" : "−";
});
runButton.addEventListener("click", () => runInvestigation());
windowSelect.addEventListener("change", () => runInvestigation());
$("#load-history-button").addEventListener("click", openSavedInvestigation);
$("#export-json-button").addEventListener("click", exportJson);
$("#export-csv-button").addEventListener("click", exportCsv);
["alert-revenue-threshold", "alert-returns-threshold", "alert-delivery-threshold"]
  .forEach((id) => $(`#${id}`).addEventListener("change", saveAlertThresholds));

function setAccessStatus(message, isError = false) {
  const element = $("#access-status");
  element.textContent = message;
  element.classList.toggle("error", isError);
}

async function supabaseAuth(path, body) {
  const response = await fetch(`${appConfig.supabase_url}/auth/v1/${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      apikey: appConfig.supabase_anon_key,
    },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.msg || result.message || result.error_description || "Authentication failed.");
  return result;
}

async function establishSession(mode) {
  try {
    const body = {
      email: $("#auth-email").value.trim(),
      password: $("#auth-password").value,
    };
    const result = mode === "signup"
      ? await supabaseAuth("signup", body)
      : await supabaseAuth("token?grant_type=password", body);
    if (!result.access_token) {
      setAccessStatus("Account created. Confirm your email, then sign in.");
      return;
    }
    accessToken = result.access_token;
    sessionStorage.setItem("biAgentAccessToken", accessToken);
    $("#auth-controls").hidden = true;
    $("#workspace-controls").hidden = false;
    setAccessStatus("Signed in. Select or create a workspace.");
    await loadTenants();
  } catch (error) {
    setAccessStatus(error.message, true);
  }
}

async function loadTenants() {
  try {
    const result = await requestJson("/api/tenants");
    const select = $("#workspace-select");
    select.replaceChildren();
    for (const tenant of result.tenants) {
      const option = document.createElement("option");
      option.value = tenant.tenant_id;
      option.textContent = `${tenant.name} (${tenant.role})`;
      select.append(option);
    }
    if (!result.tenants.length) {
      activeTenant = null;
      sessionStorage.removeItem("biAgentTenantId");
      restoreAlertThresholds();
      document.querySelector("main").hidden = true;
      setAccessStatus("Create a workspace to keep each dataset isolated.");
      return;
    }
    const selected = result.tenants.find((tenant) => tenant.tenant_id === activeTenant) || result.tenants[0];
    activeTenant = selected.tenant_id;
    sessionStorage.setItem("biAgentTenantId", activeTenant);
    select.value = activeTenant;
    restoreAlertThresholds();
    $("#shopify-controls").hidden = !appConfig.shopify_enabled;
    document.querySelector("main").hidden = false;
    await loadShopifyStatus();
    await loadDashboard();
  } catch (error) {
    if (error.message.includes("401")) signOut();
    setAccessStatus(error.message, true);
  }
}

async function createWorkspace() {
  const name = $("#workspace-name").value.trim();
  if (!name) {
    setAccessStatus("Enter a workspace name first.", true);
    return;
  }
  try {
    await requestJson("/api/tenants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    $("#workspace-name").value = "";
    setAccessStatus("Workspace created.");
    await loadTenants();
  } catch (error) {
    setAccessStatus(error.message, true);
  }
}

function signOut() {
  currentInvestigation = null;
  $("#export-json-button").disabled = true;
  $("#export-csv-button").disabled = true;
  accessToken = null;
  activeTenant = null;
  sessionStorage.removeItem("biAgentAccessToken");
  sessionStorage.removeItem("biAgentTenantId");
  $("#auth-controls").hidden = false;
  $("#workspace-controls").hidden = true;
  document.querySelector("main").hidden = true;
  setAccessStatus("Signed out.");
}

async function loadShopifyStatus() {
  if (!appConfig.shopify_enabled) return;
  try {
    const status = await requestJson("/api/shopify/status");
    $("#sync-shopify-button").hidden = !status.connected;
    $("#connect-shopify-button").hidden = status.connected;
    $("#shop-domain").hidden = status.connected;
    $("#shopify-status").textContent = status.connected
      ? `${status.shop} · ${status.currency || "currency detected on first sync"}`
      : "No store connected";
  } catch (error) {
    setAccessStatus(error.message, true);
  }
}

async function connectShopify() {
  try {
    const result = await requestJson("/api/shopify/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shop: $("#shop-domain").value.trim() }),
    });
    window.location.assign(result.authorization_url);
  } catch (error) {
    setAccessStatus(error.message, true);
  }
}

async function syncShopify() {
  const button = $("#sync-shopify-button");
  button.disabled = true;
  button.textContent = "Syncing…";
  try {
    const result = await requestJson("/api/shopify/sync", { method: "POST" });
    $("#shopify-status").textContent = `${result.active_orders.toLocaleString("en-US")} orders · ${result.currency || "no currency detected"}`;
    await loadDashboard();
  } catch (error) {
    setAccessStatus(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Sync recent orders";
  }
}

$("#auth-form").addEventListener("submit", (event) => {
  event.preventDefault();
  establishSession("signin");
});
$("#signup-button").addEventListener("click", () => establishSession("signup"));
$("#create-workspace-button").addEventListener("click", createWorkspace);
$("#workspace-select").addEventListener("change", async (event) => {
  activeTenant = event.currentTarget.value;
  sessionStorage.setItem("biAgentTenantId", activeTenant);
  await loadShopifyStatus();
  await loadDashboard();
});
$("#signout-button").addEventListener("click", signOut);
$("#connect-shopify-button").addEventListener("click", connectShopify);
$("#sync-shopify-button").addEventListener("click", syncShopify);

async function initialize() {
  try {
    appConfig = await requestJson("/api/config");
    if (appConfig.auth_enabled) {
      $("#cloud-access").hidden = false;
      document.querySelector("main").hidden = true;
      [...windowSelect.options].forEach((option) => {
        option.disabled = Number(option.value) > 30;
      });
      if (accessToken) {
        $("#auth-controls").hidden = true;
        $("#workspace-controls").hidden = false;
        await loadTenants();
      }
    } else {
      restoreAlertThresholds();
      await loadDashboard();
    }
    if (new URLSearchParams(window.location.search).has("shopify")) {
      setAccessStatus("Shopify connection completed. Sync recent orders to load data.");
      history.replaceState(null, "", window.location.pathname);
    }
  } catch (error) {
    setAccessStatus(error.message, true);
  }
  await loadEvals();
}

initialize();
