/* Carbon Payback Live: reads data/live.json (written hourly by `cao live tick`) and renders it. */
(() => {
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const KIND = { "ml-training": ["ML training", "--s1"], "batch-processing": ["batch", "--s3"], "data-pipeline": ["data-heavy", "--s2"], "web-service": ["web service", "--s7"] };
const POLICY_SLOT = { "ours-milp": "--s1", greenest: "--s2", ours: "--s3", unaware: "--s4" };
const POLICY_ORDER = ["ours-milp", "greenest", "ours", "unaware"];      // palette slot order
const TABLE_ORDER = ["ours", "ours-milp", "greenest", "unaware"];
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

function renderAll() { renderStatus(); renderHero(); renderCards(); renderForecast(); renderStage(); renderFeed(); renderScore(); buildCalc(); renderAbout(); }

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

function renderHero() {
  const o = pol("ours"), u = pol("unaware"), g = pol("greenest"), tw = LIVE.twin;
  const cut = u.total_g > 0 ? Math.round((1 - o.total_g / u.total_g) * 100) : 0;
  const stats = [
    ["lead", fmtG(u.total_g - o.total_g) + " CO₂", `avoided against running every job where it was submitted · ${cut}% lower · ${tw.hours} h on live grid data`],
    ["", fmtG(g.total_g - o.total_g), "less than always chasing the greenest grid"],
    ["", num(o.refuses), "times a greener grid was refused"],
    ["", num(tw.decisions_total), "placement decisions evaluated"],
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
function renderCards() {
  $("#locs").innerHTML = LIVE.locations.map((l) => {
    if (!l.history) {
      const why = l.status === "awaiting-key" ? "Waiting for its API key. Joins automatically once the key is set." : "No data received yet.";
      return `<div class="loc off"><div class="loc-top"><span class="loc-name">${esc(l.name)}</span><span class="cc">${esc(l.country)}</span></div><div class="loc-foot" style="display:block;line-height:1.5">${esc(why)}</div><div class="loc-foot"><span>${esc(l.operator)}</span></div></div>`;
    }
    const s = l.stats7d || {}, st = l.status === "live" ? `${ago(l.updated_at)} ago` : l.status;
    return `<button class="loc" type="button" data-id="${l.id}" aria-pressed="${l.id === selected}">
      <div class="loc-top"><span class="loc-name">${esc(l.name)}</span><span class="cc">${esc(l.country)}</span></div>
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
  $("#fc-sub").textContent = `${l.name} · ${l.operator} · last 72 hours and the next 24.`;
  const hasBand = fc.length && fc[0][1] != null;
  $("#fc-legend").innerHTML = `<span><i style="background:var(--ink-2)"></i>measured</span><span><i style="background:var(--s1)"></i>our forecast (${esc(modelName(l.forecast_model))})</span>` +
    (hasBand ? `<span><i style="background:${alpha(s1, 0.3)};height:10px"></i>80% band from recent errors</span>` : "") +
    (off.size ? `<span><i class="dash" style="color:var(--s2)"></i>operator's own forecast</span>` : "");
  renderAccuracy(l);
}
const modelName = (m) => ({ gbm: "boosted trees", blend: "blend of three", seasonal: "seasonal", persistence: "persistence" }[m] || m || "–");

function renderAccuracy(l) {
  const a = (LIVE.accuracy.per_location || {})[l.id], box = $("#acc");
  if (!a) { box.innerHTML = `<h3>Forecast accuracy</h3><p class="note">Needs ten days of history for ${esc(l.name)} before it can be scored. ${l.hours_of_history || 0} hours collected so far.</p>`; if (charts["acc-chart"]) { charts["acc-chart"].destroy(); delete charts["acc-chart"]; } return; }
  const tiles = [["our selector", a.mae_ours], ["persistence", a.mae_persistence], ["same hour yesterday", a.mae_seasonal]];
  const best = Math.min(...tiles.map((t) => t[1]));
  const d = a.last_day;
  box.innerHTML = `<h3>Forecast accuracy · ${esc(l.name)}</h3>
    <div class="acc-grid">${tiles.map(([n, v]) => `<div class="tile ${v === best ? "best" : ""}"><div class="v">${num(v, 1)}</div><div class="l">${esc(n)}</div></div>`).join("")}</div>
    <p class="note">Mean absolute error in gCO₂/kWh over the last ${a.n_days} days, 24 hours ahead, scored out of sample. Lower is better.</p>
    <div class="kv"><span>Model serving today</span><span>${esc(modelName(a.selected))}</span></div>
    <div class="kv"><span>Boosted trees alone</span><span>${num(a.mae_gbm, 1)}</span></div>
    ${a.mae_official_last_day != null ? `<div class="kv"><span>${esc(d.day)}: ours vs operator</span><span>${num(a.mae_ours_last_day, 1)} vs ${num(a.mae_official_last_day, 1)}</span></div>` : ""}
    <h3 style="margin-top:14px">${esc(d.day)}: forecast against what happened</h3>
    <div class="chart mini"><canvas id="acc-chart" aria-label="Forecast against actual for the last scored day"></canvas></div>
    <div class="legend"><span><i style="background:var(--ink-2)"></i>actual</span><span><i style="background:var(--s1)"></i>our forecast</span></div>`;
  const base = chartBase(); base.scales.x.ticks.maxTicksLimit = 5;
  base.plugins.tooltip.callbacks = { label: (it) => ` ${it.dataset.label}: ${num(it.parsed.y)} gCO₂/kWh` };
  mk("acc-chart", { type: "line", data: { labels: d.ts.map((t) => hhmm(new Date(t))), datasets: [
    { label: "actual", data: d.actual, borderColor: css("--ink-2"), borderWidth: 2, pointRadius: 0, tension: 0.25 },
    { label: "our forecast", data: d.ours, borderColor: css("--s1"), borderWidth: 2, pointRadius: 0, tension: 0.25 }] }, options: base });
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
function renderScore() {
  const tw = LIVE.twin, colIdx = Object.fromEntries(tw.series_columns.map((c, i) => [c, i + 1]));
  const labels = tw.series.map((r) => fmtT(r[0]));
  const ds = POLICY_ORDER.filter((id) => colIdx[id]).map((id) => ({ label: pol(id).label, data: tw.series.map((r) => r[colIdx[id]] / 1000), borderColor: css(POLICY_SLOT[id]), backgroundColor: css(POLICY_SLOT[id]), borderWidth: id === "ours" ? 3 : 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.15 }));
  const base = chartBase();
  base.scales.x.ticks.maxTicksLimit = 6;
  base.layout = { padding: { right: 150 } };
  base.scales.y.title = { display: true, text: "kg CO₂e, cumulative" };
  base.plugins.tooltip.callbacks = { label: (it) => ` ${it.dataset.label}: ${num(it.parsed.y, 2)} kg` };
  const ends = { id: "ends", afterDatasetsDraw(c) {
    const g = c.ctx, pts = c.data.datasets.map((d, i) => { const m = c.getDatasetMeta(i).data; const p = m[m.length - 1]; return p ? { y: p.y, x: p.x, d } : null; }).filter(Boolean).sort((a, b) => a.y - b.y);
    for (let i = 1; i < pts.length; i++) if (pts[i].y - pts[i - 1].y < 15) pts[i].y = pts[i - 1].y + 15;
    g.save(); g.font = `12px ${css("--sans")}`; g.textBaseline = "middle";
    pts.forEach((p) => { g.fillStyle = p.d.borderColor; g.beginPath(); g.arc(p.x + 8, p.y, 4, 0, 6.3); g.fill(); g.fillStyle = css("--ink"); g.fillText(p.d.label.replace("Payback-aware · ", "").replace("Payback-aware (ours)", "Ours"), p.x + 17, p.y); });
    g.restore(); } };
  mk("score-chart", { type: "line", data: { labels, datasets: ds }, options: base, plugins: [ends] });
  const head = `<tr><th>policy</th><th>total CO₂e</th><th>from running</th><th>from moving</th><th>moves made</th><th>moves refused</th><th>hours waited</th><th>jobs finished</th><th>finished late</th></tr>`;
  $("#score-table").innerHTML = head + TABLE_ORDER.map((id) => { const p = pol(id); return p ? `<tr><td><i style="background:var(${POLICY_SLOT[id]})"></i>${esc(p.label)}</td><td>${fmtG(p.total_g)}</td><td>${fmtG(p.exec_g)}</td><td>${fmtG(p.migration_g)}</td><td>${p.migrations}</td><td>${p.refuses}</td><td>${p.waits}</td><td>${p.done}</td><td>${p.deadline_missed}</td></tr>` : ""; }).join("");
  $("#score-sub").textContent = `Cumulative emissions of the same ${tw.jobs_created} jobs under each policy, since ${fmtT(tw.epoch)} UTC.`;
  $("#score-note").textContent = `Running = electricity used by the jobs. Moving = checkpoint, transfer and restore. Late = finished after its deadline. The first ${LIVE.meta.notes.replayed_hours} hours were replayed from recorded grid data when the dashboard launched.`;
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
  LIVE.locations.forEach((l) => { if (l.history && !seen.has(l.operator)) { seen.add(l.operator); const names = LIVE.locations.filter((x) => x.operator === l.operator && x.history).map((x) => x.name).join(", "); real.push(`Grid carbon intensity for ${esc(names)} from <a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.operator)}</a>`); } });
  const hrs = Math.max(...withData().map((l) => l.hours_of_history || 0));
  real.push(`Forecasts: retrained on up to ${num(hrs)} hours of that history, scored daily against what the grid then did`);
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
