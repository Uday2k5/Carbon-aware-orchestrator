/* Carbon Payback Live: reads data/live.json (written hourly by `cao live tick`) and renders it. */
(() => {
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const KIND = { "ml-training": ["ML training", "--s1"], "batch-processing": ["batch", "--s3"], "data-pipeline": ["data-heavy", "--s2"], "web-service": ["web service", "--s7"] };
const POLICY_SLOT = { "ours-milp": "--s1", greenest: "--s2", ours: "--s3", unaware: "--s4", "ours-naive": "--s5" };
const POLICY_ORDER = ["ours-milp", "greenest", "ours", "unaware", "ours-naive"];      // palette slot order
const TABLE_ORDER = ["ours", "ours-naive", "ours-milp", "greenest", "unaware"];
const SHORT = { ours: "Ours", "ours-milp": "Ours · 24 h plan", greenest: "Always greenest", unaware: "Carbon-unaware", "ours-naive": "Ours · naive forecast" };
let LIVE = null, selected = null, ciLo = 0, ciHi = 400;
const charts = {};
const jobEls = new Map();

const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const el = (n, a = {}) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); return e; };
const num = (x, d = 0) => (x == null || !isFinite(x)) ? "–" : Number(x).toLocaleString("en-GB", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmtG = (g) => g == null ? "–" : Math.abs(g) >= 1000 ? num(g / 1000, Math.abs(g) >= 100000 ? 0 : 2) + " kg" : num(g) + " g";
const hhmm = (d) => String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0");
const fmtT = (iso) => { const d = new Date(iso); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${hhmm(d)}`; };
const ago = (iso) => { const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000)); return m < 90 ? `${m} min` : m < 2880 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} d`; };
const byId = (id) => LIVE.locations.find((l) => l.id === id);
const pol = (id) => LIVE.twin.policies.find((p) => p.id === id);
const withData = () => LIVE.locations.filter((l) => l.history && l.history.length);
const ciT = (v) => Math.min(1, Math.max(0, (Math.sqrt(Math.max(v, 0)) - Math.sqrt(ciLo)) / Math.max(1e-9, Math.sqrt(ciHi) - Math.sqrt(ciLo))));
const ciColor = (v) => `color-mix(in oklab, var(--ci-high) ${(ciT(v) * 100).toFixed(0)}%, var(--ci-low))`;
const alpha = (hex, a) => { const h = hex.replace("#", ""); const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };

async function load() {
  try {
    const r = await fetch("data/live.json?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    LIVE = await r.json();
  } catch (e) {
    $("#status-text").textContent = "no data yet"; $("#status").classList.add("stale");
    return;
  }
  const lo = [], hi = [];
  withData().forEach((l) => { if (l.stats7d) { lo.push(l.stats7d.min); hi.push(l.stats7d.max); } });
  ciLo = Math.min(...lo, 0); ciHi = Math.max(...hi, 100);
  if (!selected || !byId(selected) || !byId(selected).history) selected = (byId("london") && byId("london").history) ? "london" : (withData()[0] || {}).id;
  renderAll();
}

function renderAll() { renderStatus(); renderHero(); renderCards(); renderForecast(); renderEvents(); renderStage(); renderFeed(); renderScore(); buildCalc(); renderAbout(); }
const acc = (id) => ((LIVE.accuracy || {}).per_location || {})[id];
const card = (id) => (((LIVE.models || {}).forecaster || {}).per_location || {})[id];

/* ------------------------------------------------------------------ status + hero */
function renderStatus() {
  if (!LIVE) return;
  const times = LIVE.locations.filter((l) => l.updated_at && l.status === "live").map((l) => +new Date(l.updated_at));
  const newest = times.length ? new Date(Math.max(...times)).toISOString() : LIVE.meta.generated_at;
  const mins = (Date.now() - new Date(newest)) / 60000;
  $("#status").classList.toggle("stale", mins > 150);
  $("#status-text").textContent = (mins > 150 ? "DATA " : "LIVE · grid data ") + ago(newest) + " old";
  $("#status-short").textContent = (mins > 150 ? "" : "LIVE · ") + ago(newest);
  $("#foot-text").textContent = `Last pipeline run ${fmtT(LIVE.meta.generated_at)} UTC · run #${LIVE.meta.ticks} · times shown in UTC · refreshes every hour`;
}

function skillStat() {
  const sk = Object.values((LIVE.accuracy || {}).per_location || {}).map((a) => a.skill_pct).filter((v) => v != null);
  if (!sk.length) return ["", num(LIVE.twin.decisions_total), "placement decisions evaluated"];
  const avg = sk.reduce((a, b) => a + b, 0) / sk.length;
  return ["", `${num(avg)}%`, `lower forecast error than the best naive method, average of ${sk.length} grids`];
}
function renderHero() {
  const o = pol("ours"), u = pol("unaware"), g = pol("greenest"), tw = LIVE.twin;
  const cut = u.total_g > 0 ? Math.round((1 - o.total_g / u.total_g) * 100) : 0;
  const stats = [
    ["lead", fmtG(u.total_g - o.total_g) + " CO₂", `avoided against running every job where it was submitted · ${cut}% lower · ${tw.hours} h on live grid data`],
    ["", fmtG(g.total_g - o.total_g), "less than always chasing the greenest grid"],
    ["", num(o.refuses), "times a greener grid was refused"],
    skillStat(),
    ["", `${o.migrations} vs ${g.migrations}`, "migrations: ours vs greenest-chaser"],
  ];
  $("#hero-stats").innerHTML = stats.map(([c, v, l]) => `<div class="stat ${c}"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
}

/* ------------------------------------------------------------------ location cards */
function spark(l) {
  const h = (l.history || []).map((p) => p[1]), f = (l.forecast || []).map((p) => p[2]);
  const all = h.concat(f); if (!all.length) return "";
  const mn = Math.min(...all), mx = Math.max(...all), W = 200, H = 44, n = all.length;
  const x = (i) => (i / Math.max(1, n - 1)) * W, y = (v) => H - 4 - ((v - mn) / Math.max(1e-9, mx - mn)) * (H - 8);
  const path = (arr, off) => arr.map((v, i) => `${i ? "L" : "M"}${x(i + off).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const fp = f.length ? `M${x(h.length - 1).toFixed(1)},${y(h[h.length - 1]).toFixed(1)}` + f.map((v, i) => `L${x(h.length + i).toFixed(1)},${y(v).toFixed(1)}`).join("") : "";
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><path d="${path(h, 0)}" fill="none" stroke="var(--ink-2)" stroke-width="1.6" vector-effect="non-scaling-stroke"/>${fp ? `<path d="${fp}" fill="none" stroke="var(--s1)" stroke-width="1.6" stroke-dasharray="4 3" vector-effect="non-scaling-stroke"/>` : ""}</svg>`;
}
function unusual(id) {
  const a = ((LIVE.anomalies || {}).latest || {})[id];
  return a && a.unusual ? `<span class="flag ${a.z < 0 ? "cleaner" : ""}" title="${num(a.actual)} against ${num(a.expected)} expected three hours earlier">UNUSUAL</span>` : "";
}
function estText(l) {
  const e = l.estimated || {};
  return `${e.provider || l.operator} could not measure this grid for these hours and filled them in with its own estimate${e.method ? ` (${e.method.replace(/_/g, " ").toLowerCase()})` : ""}. ${num(e.estimated_pct)}% of the last day is estimated.`;
}
function renderCards() {
  $("#locs").innerHTML = LIVE.locations.map((l) => {
    if (!l.history) {
      const why = l.status === "awaiting-key" ? "Waiting for its API key. Joins automatically once the key is set." : "No data received yet.";
      return `<div class="loc off"><div class="loc-top"><span class="loc-name">${esc(l.name)}</span><span class="cc">${esc(l.country)}</span></div><div class="loc-foot" style="display:block;line-height:1.5">${esc(why)}</div><div class="loc-foot"><span>${esc(l.operator)}</span></div></div>`;
    }
    const s = l.stats7d || {}, st = l.status === "live" ? `${ago(l.updated_at)} ago` : l.status;
    return `<button class="loc" type="button" data-id="${l.id}" aria-pressed="${l.id === selected}">
      <div class="loc-top"><span class="loc-name">${esc(l.name)}${unusual(l.id)}${l.estimated ? `<span class="flag est" title="${esc(estText(l))}">ESTIMATE</span>` : ""}</span><span class="cc">${esc(l.country)}</span></div>
      <div class="loc-ci"><span class="num">${num(l.ci_now)}</span><span class="unit">gCO₂/kWh</span><i class="swatch" style="background:${ciColor(l.ci_now)}"></i></div>
      ${spark(l)}
      <div class="loc-foot"><span title="lowest and highest in the last 7 days">7d ${num(s.min)}–${num(s.max)}</span><span class="st ${esc(l.status)}" title="age of the latest reading">${esc(st)}</span></div>
    </button>`;
  }).join("");
  document.querySelectorAll(".loc[data-id]").forEach((b) => b.addEventListener("click", () => { selected = b.dataset.id; renderCards(); renderForecast(); }));
}

/* ------------------------------------------------------------------ charts */
function chartBase() {
  Chart.defaults.font.family = css("--sans") || "sans-serif"; Chart.defaults.font.size = 12; Chart.defaults.color = css("--muted");
  return {
    responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
    plugins: { legend: { display: false }, tooltip: { backgroundColor: css("--ink"), titleColor: css("--ground"), bodyColor: css("--ground"), padding: 10, cornerRadius: 8, boxPadding: 4, usePointStyle: true } },
    scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 7, maxRotation: 0, autoSkip: true }, border: { color: css("--line") } },
              y: { grid: { color: css("--line") }, border: { display: false }, beginAtZero: true } },
  };
}
function mk(id, cfg) { if (charts[id]) charts[id].destroy(); charts[id] = new Chart($("#" + id), cfg); }

function renderForecast() {
  const l = byId(selected); if (!l) return;
  const hist = l.history || [], fc = l.forecast || [], n = hist.length;
  const labels = hist.map((p) => fmtT(p[0])).concat(fc.map((p) => fmtT(p[0])));
  const pad = (k) => Array(k).fill(null);
  const last = n ? hist[n - 1][1] : null;
  const off = new Map((l.official_forecast || []).map((p) => [fmtT(p[0]), p[1]]));
  const s1 = css("--s1"), s2 = css("--s2");
  const ds = [
    { label: "measured", data: hist.map((p) => p[1]).concat(pad(fc.length)), borderColor: css("--ink-2"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25 },
    { label: "", data: pad(n - 1).concat([last], fc.map((p) => p[1])), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, tension: 0.25 },
    { label: "", data: pad(n - 1).concat([last], fc.map((p) => p[3])), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, backgroundColor: alpha(s1, 0.16), fill: "-1", tension: 0.25 },
    { label: "our forecast", data: pad(n - 1).concat([last], fc.map((p) => p[2])), borderColor: s1, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25 },
  ];
  if (off.size) ds.push({ label: "operator's forecast", data: labels.map((t, i) => (i >= n - 1 && off.has(t)) ? off.get(t) : null), borderColor: s2, borderWidth: 2, borderDash: [5, 4], pointRadius: 0, pointHoverRadius: 4, tension: 0.25, spanGaps: true });
  const base = chartBase();
  base.plugins.tooltip.filter = (it) => it.dataset.label !== "" && it.parsed.y != null;
  base.plugins.tooltip.callbacks = { label: (it) => ` ${it.dataset.label}: ${num(it.parsed.y)} gCO₂/kWh` };
  base.scales.y.title = { display: true, text: "gCO₂ per kWh" };
  const nowLine = { id: "now", afterDatasetsDraw(c) { const x = c.scales.x.getPixelForValue(n - 1), a = c.chartArea, g = c.ctx; g.save(); g.strokeStyle = css("--muted"); g.setLineDash([3, 3]); g.beginPath(); g.moveTo(x, a.top); g.lineTo(x, a.bottom); g.stroke(); g.setLineDash([]); g.fillStyle = css("--muted"); g.font = `11px ${css("--mono")}`; g.textAlign = "right"; g.fillText("now", x - 6, a.top + 12); g.restore(); } };
  mk("fc-chart", { type: "line", data: { labels, datasets: ds }, options: base, plugins: [nowLine] });
  $("#fc-sub").textContent = `${l.name} · ${l.operator} · last 72 hours and the next 24.${l.estimated ? " Values for this grid are the provider's estimates, not measurements." : ""}`;
  const hasBand = fc.length && fc[0][1] != null;
  $("#fc-legend").innerHTML = `<span><i style="background:var(--ink-2)"></i>${l.estimated ? "provider's estimate" : "measured"}</span><span><i style="background:var(--s1)"></i>our forecast (${esc(modelName(l.forecast_model))})</span>` +
    (hasBand ? `<span><i style="background:${alpha(s1, 0.3)};height:10px"></i>80% band from recent errors</span>` : "") +
    (off.size ? `<span><i class="dash" style="color:var(--s2)"></i>operator's own forecast</span>` : "");
  renderWhy(l); renderAccuracy(l); renderModel(l);
}

function renderWhy(l) {
  const box = $("#why"), eff = l.weather_effect, wx = l.weather || [], fc = l.forecast || [];
  if (l.estimated) { box.innerHTML = `<p>${esc(estText(l))} No model is trained on estimated values, so the forecast here is "${esc(modelName(l.forecast_model))}".</p>`; return; }
  if (!eff || !wx.length || !fc.length) { box.innerHTML = l.forecast_model && l.forecast_model !== "weather-trees" ? `<p>This grid has too little history for the trained model yet, so the forecast is "${esc(modelName(l.forecast_model))}".</p>` : ""; return; }
  let k = 0; eff.forEach((v, i) => { if (Math.abs(v) > Math.abs(eff[k])) k = i; });
  const fut = wx.slice(24), windNow = (wx[23] || [])[1], windThen = (fut[k] || [])[1], when = fmtT(fc[k][0]);
  const peak = fut.reduce((a, b) => (b[1] != null && (a == null || b[1] > a[1]) ? b : a), null);
  const line = Math.abs(eff[k]) < 3
    ? `Weather is forecast to stay close to now, so the forecast mostly follows the grid's usual daily shape.`
    : `Forecast weather <b>${eff[k] < 0 ? "lowers" : "raises"}</b> the prediction by up to <b>${num(Math.abs(eff[k]))} gCO₂/kWh</b> around ${when}: wind ${num(windNow, 1)} → ${num(windThen, 1)} m/s.`;
  box.innerHTML = `<p><span class="badge">why</span> ${line}</p><div class="chart mini" style="height:110px"><canvas id="wx-chart" aria-label="Wind forecast"></canvas></div>
    <div class="legend"><span><i style="background:var(--s3)"></i>wind at 100 m, m/s: last 24 h and day-ahead forecast${peak ? ` (peak ${num(peak[1], 1)} m/s at ${fmtT(peak[0])})` : ""}</span></div>`;
  const base = chartBase(); base.scales.x.ticks.maxTicksLimit = 6; base.scales.y.ticks = { maxTicksLimit: 3 };
  base.plugins.tooltip.callbacks = { label: (it) => ` wind: ${num(it.parsed.y, 1)} m/s` };
  const nowLine = { id: "nowx", afterDatasetsDraw(c) { const x = c.scales.x.getPixelForValue(23), a = c.chartArea, g = c.ctx; g.save(); g.strokeStyle = css("--muted"); g.setLineDash([3, 3]); g.beginPath(); g.moveTo(x, a.top); g.lineTo(x, a.bottom); g.stroke(); g.restore(); } };
  mk("wx-chart", { type: "line", data: { labels: wx.map((r) => fmtT(r[0])), datasets: [{ label: "wind", data: wx.map((r) => r[1]), borderColor: css("--s3"), backgroundColor: alpha(css("--s3"), 0.12), fill: true, borderWidth: 2, pointRadius: 0, tension: 0.3 }] }, options: base, plugins: [nowLine] });
}
const modelName = (m) => ({ "weather-trees": "weather-driven trees", trees: "boosted trees", seasonal: "same hour yesterday", persistence: "same as now" }[m] || m || "–");

function renderAccuracy(l) {
  const a = acc(l.id), box = $("#acc");
  ["acc-chart", "hz-chart"].forEach((id) => { if (charts[id]) { charts[id].destroy(); delete charts[id]; } });
  if (l.estimated) { box.innerHTML = `<h3>Forecast accuracy</h3><p class="note">Not scored for ${esc(l.name)}. Its values are estimates that follow a typical daily pattern, so a forecast would look accurate without having learned anything about the real grid. The accuracy figures on this page cover measured grids only.</p>`; return; }
  if (!a) { box.innerHTML = `<h3>Forecast accuracy</h3><p class="note">Needs four weeks of history for ${esc(l.name)} before the trained model can be scored. ${l.hours_of_history || 0} hours collected so far.</p>`; return; }
  const tiles = [["our model", a.mae_ours], ["same as now", a.mae_persistence], ["same hour yesterday", a.mae_seasonal]];
  const best = Math.min(...tiles.map((t) => t[1])), d = a.last_day;
  box.innerHTML = `<h3>Forecast accuracy · ${esc(l.name)} <span class="badge ${a.skill_pct > 0 ? "" : "flat"}" style="margin-left:6px">${a.skill_pct > 0 ? num(a.skill_pct) + "% better than best naive" : "level with naive"}</span></h3>
    <div class="acc-grid">${tiles.map(([n, v]) => `<div class="tile ${v === best ? "best" : ""}"><div class="v">${num(v, 1)}</div><div class="l">${esc(n)}</div></div>`).join("")}</div>
    <p class="note">Mean error in gCO₂/kWh, 24 hours ahead. ${a.n_forecasts} forecasts over the last ${a.n_days} days, each made by a model that had not seen that day. Lower is better.</p>
    ${bandLine(l.id, a)}
    ${trackLine(l.id)}
    ${a.mae_official_last_day != null ? `<div class="kv"><span>${esc(d.day)}: ours vs operator's forecast</span><span>${num(a.mae_ours_last_day, 1)} vs ${num(a.mae_official_last_day, 1)}</span></div>` : ""}
    <h3 class="gap">Error by hours ahead</h3>
    <div class="chart mini"><canvas id="hz-chart" aria-label="Forecast error by hours ahead"></canvas></div>
    <div class="legend"><span><i style="background:var(--s1)"></i>our model</span><span><i class="dash" style="color:var(--ink-2)"></i>same as now</span></div>
    ${d ? `<h3 class="gap">${esc(d.day)}: forecast against what happened</h3>
    <div class="chart mini"><canvas id="acc-chart" aria-label="Forecast against actual for the last scored day"></canvas></div>
    <div class="legend"><span><i style="background:var(--ink-2)"></i>actual</span><span><i style="background:var(--s1)"></i>our forecast, made the evening before</span></div>` : ""}`;
  const hz = chartBase(); hz.scales.x.ticks.maxTicksLimit = 6; hz.scales.x.title = { display: true, text: "hours ahead" };
  hz.plugins.tooltip.callbacks = { title: (it) => `${it[0].label} h ahead`, label: (it) => ` ${it.dataset.label}: ${num(it.parsed.y, 1)} gCO₂/kWh` };
  mk("hz-chart", { type: "line", data: { labels: a.by_horizon.ours.map((_, i) => i + 1), datasets: [
    { label: "our model", data: a.by_horizon.ours, borderColor: css("--s1"), borderWidth: 2, pointRadius: 0, tension: 0.25 },
    { label: "same as now", data: a.by_horizon.persistence, borderColor: css("--ink-2"), borderWidth: 2, borderDash: [5, 4], pointRadius: 0, tension: 0.25 }] }, options: hz });
  if (!d) return;
  const base = chartBase(); base.scales.x.ticks.maxTicksLimit = 5;
  base.plugins.tooltip.callbacks = { label: (it) => ` ${it.dataset.label}: ${num(it.parsed.y)} gCO₂/kWh` };
  mk("acc-chart", { type: "line", data: { labels: d.ts.map((t) => hhmm(new Date(t))), datasets: [
    { label: "actual", data: d.actual, borderColor: css("--ink-2"), borderWidth: 2, pointRadius: 0, tension: 0.25 },
    { label: "our forecast", data: d.ours, borderColor: css("--s1"), borderWidth: 2, pointRadius: 0, tension: 0.25 }] }, options: base });
}

function bandLine(id, a) {
  const rc = ((LIVE.track || {})[id] || {}).recal;
  if (rc) return `<div class="kv"><span>Shaded band held the true value</span><span>${num(rc.hit_pct)}% of ${num(rc.n)} checked forecasts (aim ${num(rc.target_pct)}%) · ${num(rc.model_band_hit_pct)}% before live recalibration</span></div>`;
  return a.band_hit_pct != null ? `<div class="kv"><span>Shaded band held the true value</span><span>${num(a.band_hit_pct)}% of unseen hours (aim 80%)</span></div>` : "";
}
function trackLine(id) {
  const t = (LIVE.track || {})[id];
  if (!t || !t.live_scored) return `<div class="kv"><span>Live track record</span><span>starts once today's forecasts can be checked</span></div>`;
  return `<div class="kv"><span>Live track record since ${fmtT(t.since)}</span><span>${num(t.live_scored)} forecasts checked · error ${num(t.mae, 1)} vs ${num(t.naive_mae, 1)} naive</span></div>`;
}

/* ------------------------------------------------------------------ anomaly detector */
function renderEvents() {
  const an = LIVE.anomalies || {}, list = $("#event-list"), side = $("#event-side"), nm = (id) => (byId(id) || {}).name || id;
  if (!an.hours_checked) { list.innerHTML = `<li>The detector needs a few hours of logged forecasts before it can judge anything.</li>`; side.innerHTML = ""; return; }
  $("#events-sub").textContent = `Hours when a grid landed far from where the model expected it ${an.lead_h} hours earlier. ${num(an.hours_checked)} grid-hours checked in the last two weeks, ${num(an.alarm_rate_pct, 1)}% flagged.`;
  list.innerHTML = (an.events || []).slice(0, 14).map((e) => {
    const span = e.hours > 1 ? `${fmtT(e.start)} to ${hhmm(new Date(e.end))}, ${e.hours} h` : fmtT(e.peak);
    const band = e.band && e.band[0] != null ? ` (band ${num(e.band[0])}–${num(e.band[1])})` : "";
    return `<li><div class="row1"><span class="chip ${e.direction === "dirtier" ? "REFUSE" : "MOVE"}">${e.direction === "dirtier" ? "DIRTIER" : "CLEANER"}</span><span class="job-id">${esc(nm(e.location))}</span>${e.ongoing ? `<span class="badge">now</span>` : ""}<span class="when">${span}</span></div>
      <div class="route"><b>${num(e.actual)}</b> gCO₂/kWh where the model expected ${num(e.expected)}${band} · ${num(Math.abs(e.z), 1)}× the usual error, alarm line ${num(e.limit, 1)}×</div><div class="why">${esc(e.why.text)}</div></li>`;
  }).join("") || `<li>No unusual hours in the last 7 days. Every grid stayed within what the model considers normal.</li>`;
  const SPAN = 1.6, mark = 50 / SPAN;                              // bar length = gap as a share of that grid's own alarm line
  const rows = LIVE.locations.filter((l) => (an.latest || {})[l.id]).map((l) => {
    const x = an.latest[l.id], share = Math.abs(x.z) / x.limit, w = Math.min(SPAN, share) * mark, left = x.z >= 0 ? 50 : 50 - w;
    const col = x.unusual ? (x.z > 0 ? "var(--refuse)" : "var(--move)") : "var(--muted)";
    return `<div class="zrow"><span>${esc(l.name)}</span><div class="ztrack" title="${num(x.actual)} against ${num(x.expected)} expected, ${num(Math.abs(x.z), 1)}× the usual error, alarm line ${num(x.limit, 1)}×"><i class="zmid"></i><i class="zfill" style="left:${left}%;width:${w}%;background:${col}"></i><i class="zmark" style="left:${50 + mark}%"></i><i class="zmark" style="left:${50 - mark}%"></i></div><span>${num(share * 100)}%</span></div>`;
  }).join("");
  const per = an.per_location || {};
  side.innerHTML = `<h3>How close is each grid to its alarm line</h3>
    <div class="gen">${rows}</div>
    <p class="note">Latest checked hour. The bar is the gap between the grid and the forecast made ${an.lead_h} hours earlier, as a share of that grid's alarm line. Left is cleaner than expected, right is dirtier. Past a mark and outside the forecast band counts as unusual.</p>
    <h3 class="gap">How it works</h3>
    <ul class="plain"><li>Built on the forecaster: every forecast is logged, then compared with what the grid did.</li><li>The gap is measured in units of that grid's own usual forecast error over the last two weeks.</li><li>The alarm line is ${an.threshold}× the usual error, raised on jumpy grids to the level only about ${num(an.rare_pct)} hour in 100 crosses. A volatile grid is not flagged for being itself.</li><li>Each event gets a first explanation: the wind that blew against the wind that was forecast.</li></ul>
    <div class="scroll"><table class="mini-t" style="margin-top:10px"><tr><th>grid</th><th>flagged</th><th>usual error</th><th>alarm line</th></tr>${LIVE.locations.filter((l) => per[l.id]).map((l) => `<tr><td>${esc(l.name)}</td><td>${per[l.id].flagged} of ${per[l.id].hours_checked}</td><td>${num(per[l.id].scale_g, 1)} g</td><td>${num(per[l.id].limit * per[l.id].scale_g)} g (${num(per[l.id].limit, 1)}×)</td></tr>`).join("")}</table></div>`;
}

/* ------------------------------------------------------------------ the model */
function barRow(label, value, max, color, unit = "") {
  return `<div class="bar-row"><span>${esc(label)}</span><div class="track"><div class="fill" style="width:${Math.max(1.5, value / Math.max(max, 1e-9) * 100)}%;background:${color}"></div></div><span>${num(value, value < 100 ? 1 : 0)}${unit}</span></div>`;
}
function renderModel(l) {
  const f = (LIVE.models || {}).forecaster, c = card(l.id), a = acc(l.id), left = $("#model-card"), right = $("#model-side");
  if (!f) { left.innerHTML = right.innerHTML = ""; return; }
  $("#model-sub").textContent = `Trained by this project and retrained on every run. Last trained ${fmtT(f.retrained)} UTC. Showing ${l.name}.`;
  if (l.estimated) {
    left.innerHTML = `<h3>${esc(f.name)}</h3><p class="note">No model is trained for ${esc(l.name)}: its carbon values are the provider's estimates, not measurements. Its forecast is a naive one. Pick another grid to see a trained model.</p>`;
    right.innerHTML = valueBlock(); return;
  }
  if (!c) {
    left.innerHTML = `<h3>${esc(f.name)}</h3><p class="note">${esc(l.name)} does not have four weeks of history yet, so no model is trained for it. Until then its forecast is a naive one. Pick another grid to see a trained model.</p>`;
    right.innerHTML = valueBlock(); return;
  }
  const gmax = Math.max(c.train_mae, c.val_mae_trees, c.val_mae, c.val_mae_persistence, a ? a.mae_ours : 0);
  const bands = Object.entries(c.blend).map(([b, w]) => `<tr><td>${b.replace(/^(\d+)-\1$/, "$1")} h ahead</td><td>${num(w.trees * 100)}%</td><td>${num(w.yesterday * 100)}%</td></tr>`).join("");
  left.innerHTML = `<h3>${esc(f.name)}</h3>
    <div class="facts">
      <div class="kv"><span>Predicts</span><span>${esc(f.predicts)}</span></div>
      <div class="kv"><span>Algorithm</span><span>${esc(f.algorithm)}</span></div>
      <div class="kv"><span>Inputs</span><span>${esc(f.inputs)} · weather from ${esc(f.weather_source)}</span></div>
      <div class="kv"><span>Trained on</span><span>${num(c.rows)} examples from ${num(c.hours)} hours of ${esc(l.name)} data · ${c.rounds} boosting rounds</span></div>
      <div class="kv"><span>Guard against overfitting</span><span>${esc(f.validation)}</span></div>
      <div class="kv"><span>Uncertainty band</span><span>${esc(f.uncertainty || "")}${uncLine(l.id, c, a)}</span></div>
    </div>
    <h3>Does it generalise? Error in gCO₂/kWh</h3>
    <div class="gen">
      ${barRow("days it trained on", c.train_mae, gmax, "var(--muted)")}
      ${barRow("14 held-out days, trees", c.val_mae_trees, gmax, "var(--s1)")}
      ${barRow("held-out days, after blend", c.val_mae, gmax, "var(--s1)")}
      ${a ? barRow("live walk-forward test", a.mae_ours, gmax, "var(--s3)") : ""}
      ${barRow("same as now, held-out", c.val_mae_persistence, gmax, "var(--ink-2)")}
    </div>
    <p class="note">Error on days it has seen is lower than on days it has not, as for any model, but the gap is modest and unseen-day error stays below the naive method. A memorising model would show a tiny first bar and a huge second one.</p>`;
  const dmax = Math.max(...c.drivers.map((x) => x.importance), 1e-9);
  right.innerHTML = `<h3>What drives it · ${esc(l.name)}</h3>
    <div class="gen">${c.drivers.map((x) => barRow(x.name, x.importance, dmax, "var(--s3)")).join("")}</div>
    <p class="note">How much the held-out error rises when that input is scrambled. Bigger means the model leans on it more.</p>
    <h3 class="gap">How far it trusts itself</h3>
    <div class="scroll"><table class="mini-t"><tr><th>horizon</th><th>weight on the trees' change</th><th>pull towards yesterday</th></tr>${bands}</table></div>
    <p class="note">Learned on held-out days. Where the trees do not clearly beat "same as now", the weight drops to zero by itself.</p>
    ${valueBlock()}`;
}
function uncLine(id, c, a) {
  const rc = ((LIVE.track || {})[id] || {}).recal, w = ((LIVE.track || {})[id] || {}).widen_now;
  let t = c.val_band_coverage != null ? ` · held ${num(c.val_band_coverage * 100)}% of held-out hours` : "";
  if (rc) t += `; on later forecasts ${num(rc.model_band_hit_pct)}% on its own and ${num(rc.hit_pct)}% once recalibrated (aim ${num(rc.target_pct)}%)`;
  else if (a && a.band_hit_pct != null) t += ` and ${num(a.band_hit_pct)}% of unseen ones (aim 80%)`;
  const most = w ? Math.max(...Object.values(w)) : null;
  if (most != null) t += most > 0 ? `. Right now the band is widened by up to ±${num(most, 1)} g` : `. Right now the model's own band is holding, so nothing is added`;
  return t;
}
function valueBlock() {
  const v = (LIVE.accuracy || {}).forecast_value; if (!v) return "";
  const mx = Math.max(v.naive_g, v.model_g, v.perfect_g);
  const line = v.saved_pct > 0.2
    ? `Same scheduler and same jobs on ${v.days} days of real grid data: our forecast lowers emissions by <b>${num(v.saved_pct, 1)}%</b> against a naive forecast. Perfect foresight would reach ${num(v.perfect_pct, 1)}%, so the model captures ${v.captured_pct != null ? num(v.captured_pct) + "%" : "part"} of what is possible.`
    : `On these ${v.days} days the forecast made no measurable difference to emissions; perfect foresight would have saved ${num(v.perfect_pct, 1)}%.`;
  return `<h3 class="gap">What the forecast is worth to the scheduler</h3>
    <div class="gen">
      ${barRow("naive forecast", v.naive_g / 1000, mx / 1000, "var(--s5)", " kg")}
      ${barRow("our model", v.model_g / 1000, mx / 1000, "var(--s3)", " kg")}
      ${barRow("perfect foresight", v.perfect_g / 1000, mx / 1000, "var(--ink-2)", " kg")}
    </div>
    <p class="value-line">${line}</p>
    <p class="note">${fmtT(v.from)} to ${fmtT(v.to)} UTC, averaged over ${v.streams} independent job streams. Each hour used the model that existed at that hour. New jobs stop two days before the end so every variant finishes the same work. Waiting for cleaner hours is a small lever here; most of the saving on the scoreboard comes from refusing moves that do not pay back.</p>`;
}

/* ------------------------------------------------------------------ scheduler stage + feed */
function renderStage() {
  const svg = $("#stage"), locs = withData(), cw = 1000 / Math.max(1, locs.length);
  let cols = $("#stage-cols", svg), jobsG = $("#stage-jobs", svg);
  if (!cols) { cols = el("g", { id: "stage-cols" }); jobsG = el("g", { id: "stage-jobs" }); svg.append(cols, jobsG); }
  cols.innerHTML = "";
  locs.forEach((l, i) => {
    cols.append(el("rect", { x: i * cw + 4, y: 0, width: cw - 8, height: 430, rx: 14, fill: ciColor(l.ci_now), opacity: 0.42 }));
    const t1 = el("text", { x: i * cw + cw / 2, y: 32, "text-anchor": "middle", class: "col-name" }); t1.textContent = l.name.replace("North West England", "NW England");
    const t2 = el("text", { x: i * cw + cw / 2, y: 56, "text-anchor": "middle", class: "col-ci" }); t2.textContent = `${num(l.ci_now)} g/kWh`;
    cols.append(t1, t2);
  });
  const idx = new Map(locs.map((l, i) => [l.id, i])), occ = locs.map(() => []);
  const jobs = LIVE.twin.jobs.filter((j) => idx.has(j.region));
  jobs.forEach((j) => occ[idx.get(j.region)].push(j));
  const seen = new Set();
  occ.forEach((list, i) => {
    const ncol = Math.max(1, Math.floor((cw - 24) / 78)), cell = (cw - 24) / ncol, rows = Math.max(1, Math.ceil(list.length / ncol)), rowH = Math.min(86, 340 / rows);
    list.forEach((j, q) => {
      seen.add(j.job_id);
      const x = i * cw + 12 + cell * (q % ncol) + cell / 2, y = 84 + rowH * Math.floor(q / ncol) + rowH / 2;
      let E = jobEls.get(j.job_id);
      if (!E) {
        const g = el("g", { class: "job" }), ring = el("circle", { fill: "none", "stroke-width": 3 }), body = el("circle", { "stroke-width": 2 }), lb = el("text", { "text-anchor": "middle", class: "jlabel" });
        g.append(ring, body, lb); jobsG.append(g); E = { g, ring, body, lb }; jobEls.set(j.job_id, E);
        g.addEventListener("mousemove", (e) => tip(e, j.job_id)); g.addEventListener("mouseleave", () => { $("#tip").hidden = true; });
      }
      const r = Math.min(30, 9 + 3 * Math.sqrt(j.state_gb)), col = `var(${(KIND[j.kind] || ["", "--s1"])[1]})`, run = j.status === "running";
      E.g.style.transform = `translate(${x}px,${y}px)`;
      E.body.setAttribute("r", r); E.body.setAttribute("fill", col); E.body.setAttribute("fill-opacity", run ? 0.95 : 0.2);
      E.body.setAttribute("stroke", run ? "var(--surface)" : col); E.body.setAttribute("stroke-dasharray", run ? "" : "4 3");
      const act = (j.last || "").split("|")[0];
      E.ring.setAttribute("r", r + 7); E.ring.setAttribute("stroke", act === "WAIT" ? "var(--wait)" : act === "REFUSE" ? "var(--refuse)" : "none");
      E.lb.setAttribute("y", r + 19); E.lb.textContent = j.job_id.replace(/-\d{4}(\d{2})/, "-$1");
    });
  });
  for (const [id, E] of jobEls) if (!seen.has(id)) { E.g.remove(); jobEls.delete(id); }
  $("#stage-legend").innerHTML = Object.values(KIND).map(([n, v]) => `<span><i class="sq" style="background:var(${v})"></i>${n}</span>`).join("") +
    `<span>size grows with state to move</span><span><i class="sq" style="background:transparent;border:2px dashed var(--muted)"></i>waiting</span><span><i class="sq" style="background:transparent;border:2.5px solid var(--refuse)"></i>move refused</span><span>column shade follows carbon intensity</span>`;
}
function tip(e, id) {
  const j = LIVE.twin.jobs.find((x) => x.job_id === id); if (!j) return;
  const last = LIVE.twin.decisions.find((d) => d.job === id), t = $("#tip");
  t.innerHTML = `<b>${esc(j.job_id)}</b> · ${esc((KIND[j.kind] || [j.kind])[0])}<br>${num(j.state_gb, 1)} GB state · ${num(j.power_kw * 1000)} W` +
    (j.remaining_h != null ? ` · ${num(j.remaining_h, 1)} h left` : "") + (j.sla_ms ? `<br>latency limit ${num(j.sla_ms)} ms from ${esc((byId(j.user) || {}).name || j.user)}` : "") +
    `<br>${esc(j.status)} in ${esc((byId(j.region) || {}).name || j.region)} · ${fmtG(j.carbon_g)} so far` + (last ? `<br>${esc(last.action)} at ${fmtT(last.ts)}` : "");
  t.hidden = false; t.style.left = Math.min(window.innerWidth - 320, e.clientX + 14) + "px"; t.style.top = (e.clientY + 14) + "px";
}
function renderFeed() {
  const nm = (id) => (byId(id) || {}).name || id || "";
  const rows = LIVE.twin.decisions.filter((d) => !(d.action === "REFUSE" && d.saved_g < 1)).slice(0, 40);
  $("#feed").innerHTML = rows.map((d) => {
    const route = d.action === "WAIT" ? `stays in ${esc(nm(d.from))}${d.to && d.to !== d.from ? `, then ${esc(nm(d.to))}` : ""}` : `${esc(nm(d.from))} → ${esc(nm(d.to))}`;
    const why = d.action === "WAIT" ? `resumes ${d.resume_at ? fmtT(d.resume_at) : "later"} · saves ${fmtG(d.saved_g)}`
      : `saves ${fmtG(d.saved_g)} · move costs ${fmtG(d.migration_g)} · payback ${d.payback_h == null ? "never" : num(d.payback_h, 2) + " h"} · ${num(d.remaining_h, 1)} h left`;
    return `<li><div class="row1"><span class="chip ${d.action}">${d.action}</span><span class="job-id">${esc(d.job)}</span><span class="muted" style="font-size:12px;color:var(--muted)">${num(d.state_gb, 1)} GB</span><span class="when">${fmtT(d.ts)}</span></div><div class="route">${route}</div><div class="why">${why}</div></li>`;
  }).join("") || `<li>No moves, waits or refusals yet.</li>`;
}

/* ------------------------------------------------------------------ scoreboard */
function estGrids() { return LIVE.locations.filter((l) => l.estimated).map((l) => l.name); }
function renderScore() {
  const tw = LIVE.twin, colIdx = Object.fromEntries(tw.series_columns.map((c, i) => [c, i + 1]));
  const labels = tw.series.map((r) => fmtT(r[0]));
  const ds = POLICY_ORDER.filter((id) => colIdx[id]).map((id) => ({ label: SHORT[id] || pol(id).label, pid: id, data: tw.series.map((r) => r[colIdx[id]] / 1000), borderColor: css(POLICY_SLOT[id]), backgroundColor: css(POLICY_SLOT[id]), borderWidth: id === "ours" ? 3 : 2, borderDash: id === "ours-naive" ? [5, 4] : [], pointRadius: 0, pointHoverRadius: 4, tension: 0.15 }));
  const base = chartBase();
  base.scales.x.ticks.maxTicksLimit = 6;
  base.layout = { padding: { right: 150 } };
  base.scales.y.title = { display: true, text: "kg CO₂e, cumulative" };
  base.plugins.tooltip.callbacks = { label: (it) => ` ${it.dataset.label}: ${num(it.parsed.y, 2)} kg` };
  const ends = { id: "ends", afterDatasetsDraw(c) {
    const g = c.ctx, pts = c.data.datasets.map((d, i) => { const m = c.getDatasetMeta(i).data; const p = m[m.length - 1]; return (p && d.pid !== "ours-naive") ? { y: p.y, x: p.x, d } : null; }).filter(Boolean).sort((a, b) => a.y - b.y);
    for (let i = 1; i < pts.length; i++) if (pts[i].y - pts[i - 1].y < 15) pts[i].y = pts[i - 1].y + 15;
    g.save(); g.font = `12px ${css("--sans")}`; g.textBaseline = "middle";
    pts.forEach((p) => { g.fillStyle = p.d.borderColor; g.beginPath(); g.arc(p.x + 8, p.y, 4, 0, 6.3); g.fill(); g.fillStyle = css("--ink"); g.fillText(p.d.label, p.x + 17, p.y); });
    g.restore(); } };
  mk("score-chart", { type: "line", data: { labels, datasets: ds }, options: base, plugins: [ends] });
  $("#score-legend").innerHTML = POLICY_ORDER.filter((id) => colIdx[id]).map((id) => `<span><i ${id === "ours-naive" ? `class="dash" style="color:var(${POLICY_SLOT[id]})"` : `style="background:var(${POLICY_SLOT[id]})"`}></i>${esc(SHORT[id])}</span>`).join("");
  const head = `<tr><th>policy</th><th>total CO₂e</th><th>from running</th><th>from moving</th><th>moves made</th><th>moves refused</th><th>hours waited</th><th>job-hours run</th><th>jobs finished</th><th>finished late</th></tr>`;
  $("#score-table").innerHTML = head + TABLE_ORDER.map((id) => { const p = pol(id); return p ? `<tr><td><i style="background:var(${POLICY_SLOT[id]})"></i>${esc(p.label)}${p.solver_fallbacks ? ` <span class="warn" title="The optimiser could not run for ${p.solver_fallbacks} hours; the greedy rule decided instead">· solver fell back ${p.solver_fallbacks}×</span>` : ""}</td><td>${fmtG(p.total_g)}</td><td>${fmtG(p.exec_g)}</td><td>${fmtG(p.migration_g)}</td><td>${p.migrations}</td><td>${p.refuses}</td><td>${p.waits}</td><td>${num(p.job_hours)}</td><td>${p.done}</td><td>${p.deadline_missed}</td></tr>` : ""; }).join("");
  $("#score-sub").textContent = `Cumulative emissions of the same ${tw.jobs_created} jobs under each policy, since ${fmtT(tw.epoch)} UTC.`;
  $("#score-note").textContent = `"Naive forecast" is our same rule fed "same as now" instead of the trained model, so the gap between those two lines is the model's contribution. Running = electricity used by the jobs. Moving = checkpoint, transfer and restore. Late = finished after its deadline. The first ${LIVE.meta.notes.replayed_hours} hours were replayed from recorded grid data when the dashboard launched.${estGrids().length ? ` ${estGrids().join(", ")}: carbon values are provider estimates, not measurements; jobs placed there are charged at those estimates.` : ""}`;
}

/* ------------------------------------------------------------------ payback calculator */
function buildCalc() {
  const locs = withData().filter((l) => l.ci_now != null), from = $("#c-from"), to = $("#c-to");
  const keepF = from.value, keepT = to.value;
  const opts = locs.map((l) => `<option value="${l.id}">${esc(l.name)} · ${num(l.ci_now)} g</option>`).join("");
  from.innerHTML = opts; to.innerHTML = opts;
  const sorted = [...locs].sort((a, b) => b.ci_now - a.ci_now);
  from.value = locs.some((l) => l.id === keepF) ? keepF : (sorted[0] || {}).id; to.value = locs.some((l) => l.id === keepT) ? keepT : (sorted[sorted.length - 1] || {}).id;
  calc();
}
function calc() {
  const m = LIVE.cost_model, a = byId($("#c-from").value), b = byId($("#c-to").value); if (!a || !b) return;
  const S = Math.pow(10, +$("#c-state").value), left = +$("#c-left").value, P = +$("#c-power").value;
  $("#o-state").textContent = `${num(S, S < 10 ? 1 : 0)} GB`; $("#o-left").textContent = `${num(left, 2)} h`; $("#o-power").textContent = `${num(P * 1000)} W`;
  const kwh = (j) => j / 3.6e6, ph = (p) => Math.max(0, p[0] * S + p[1]);
  const ciNet = m.network_ci === "src" ? a.ci_now : m.network_ci === "dst" ? b.ci_now : (a.ci_now + b.ci_now) / 2;
  const net = S * m.network_kwh_per_gb * ciNet, comp = kwh(ph(m.checkpoint) + ph(m.transfer)) * a.ci_now + kwh(ph(m.restore)) * b.ci_now;
  const cost = net + comp, rate = P * (a.ci_now - b.ci_now), saved = rate * left, pb = rate > 0 ? cost / rate : Infinity;
  const verdict = rate <= 0 ? "HOLD" : saved > cost ? "MOVE" : "REFUSE", mx = Math.max(saved, cost, 1);
  const line = verdict === "HOLD" ? `${esc(b.name)} is not cleaner than ${esc(a.name)} right now, so there is nothing to gain.`
    : verdict === "MOVE" ? `The move pays for itself after ${num(pb, 2)} h and the job still has ${num(left, 2)} h to run.`
    : `The move would need ${num(pb, 1)} h to pay back, but the job only has ${num(left, 2)} h left.`;
  $("#verdict").innerHTML = `<div class="big"><span class="chip ${verdict}">${verdict}</span><span class="pb">${isFinite(pb) ? "payback " + num(pb, 2) + " h" : "no payback"}</span></div>
    <p style="margin:0">${line}</p>
    <div class="bars">
      <div class="bar-row"><span>Saved by moving</span><div class="track"><div class="fill" style="width:${Math.max(0, saved) / mx * 100}%;background:var(--s3)"></div></div><span>${fmtG(Math.max(0, saved))}</span></div>
      <div class="bar-row"><span>Cost of moving</span><div class="track"><div class="fill" style="width:${cost / mx * 100}%;background:var(--s2)"></div></div><span>${fmtG(cost)}</span></div>
    </div>
    <p class="note">${esc(a.name)} ${num(a.ci_now)} → ${esc(b.name)} ${num(b.ci_now)} gCO₂/kWh. Moving ${num(S, 1)} GB: network ${fmtG(net)}, checkpoint and restore ${fmtG(comp)}. Network energy ${m.network_kwh_per_gb} kWh per GB; cost constants: ${esc(m.source)}.</p>`;
}

/* ------------------------------------------------------------------ method */
function renderAbout() {
  const n = LIVE.meta.notes, seen = new Set(), real = [];
  LIVE.locations.forEach((l) => { if (l.history && !seen.has(l.operator)) { seen.add(l.operator); const names = LIVE.locations.filter((x) => x.operator === l.operator && x.history).map((x) => x.name).join(", "); real.push(`Grid carbon intensity for ${esc(names)} from <a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.operator)}</a>${l.estimated ? " (the provider's estimate for each hour, not a measurement)" : ""}`); } });
  const hrs = Math.max(...withData().map((l) => l.hours_of_history || 0));
  real.push(`Weather forecasts for each grid from <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a>, as issued a day ahead`);
  real.push(`The forecaster: trained here on up to ${num(hrs)} hours of that history per grid, retrained every run, scored daily on days it has not seen`);
  real.push("Forecast log: every forecast is written down when issued and scored when the hour arrives");
  real.push("Uncertainty band: recalibrated on each run from the last week of checked forecasts");
  real.push("Anomaly detector: flags hours where the grid landed far outside what the model expected");
  real.push("Every decision: computed by the same engine the simulator and the Kubernetes controller use");
  real.push("Emission totals: each policy is charged for running and for moving, whether or not it counted the cost");
  $("#real-list").innerHTML = real.map((x) => `<li>${x}</li>`).join("");
  const sim = ["The jobs: generated ML training, batch, data-heavy and web workloads, identical for every policy",
    "The grids as data-centre sites: one emulated site per grid",
    `Migration cost constants: ${esc(n.cost_model)}; measured values replace them after the profiler runs on the testbed`,
    `Network energy: ${LIVE.cost_model.network_kwh_per_gb} kWh per GB moved, a published upper-range figure`,
    "Latency between sites: illustrative round-trip times"];
  const waiting = LIVE.locations.filter((l) => !l.history).map((l) => l.name);
  if (waiting.length) sim.push(`Not live yet: ${esc(waiting.join(", "))}`);
  $("#sim-list").innerHTML = sim.map((x) => `<li>${x}</li>`).join("");
  $("#about-meta").textContent = `Scheduler has run on live data since ${fmtT(LIVE.meta.first_tick)} UTC.`;
  if (LIVE.meta.repo_url) $("#repo").href = LIVE.meta.repo_url;
}

/* ------------------------------------------------------------------ wiring */
["c-from", "c-to", "c-state", "c-left", "c-power"].forEach((id) => $("#" + id).addEventListener("input", () => LIVE && calc()));
$("#theme").addEventListener("click", () => {
  const root = document.documentElement, dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("cpl-theme", root.dataset.theme); } catch (e) { /* private mode */ }
  if (LIVE) { renderForecast(); renderScore(); }
});
try { const t = localStorage.getItem("cpl-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* ignore */ }
load();
setInterval(load, 5 * 60 * 1000);
setInterval(renderStatus, 30 * 1000);
})();
