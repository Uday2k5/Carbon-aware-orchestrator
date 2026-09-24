// Builds docs/presentation/mid-eval.pptx (14 minimal slides, no speaker notes).
//   npm install pptxgenjs   (once)      node docs/presentation/build_deck.js
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const HERE = __dirname;
const ROOT = path.resolve(HERE, "..", "..");
const OUT = path.join(HERE, "mid-eval.pptx");

const C = {
  ink: "1F2A26", muted: "6B7A74", pine: "173F35", leaf: "237F52", amber: "C46A1F", teal: "1E6FB8",
  surface: "F1F5F3", white: "FFFFFF", line: "D9E2DD", paleAmber: "FBF1E4",
  move: "1B7FB0", wait: "9A6B00", refuse: "C42F4E", hold: "6B7A74",
};
const F = { head: "Cambria", body: "Calibri" };
const lum = (h) => [0, 2, 4].map((i) => parseInt(h.substr(i, 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4))).reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
const textOn = (h) => (lum(h) > 0.35 ? C.ink : C.white);

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625 in
pres.title = "Carbon-Aware Autonomous Workload Orchestrator";

function slideBase(title, dark = false) {
  const s = pres.addSlide();
  s.background = { color: dark ? C.pine : C.white };
  if (title) s.addText(title, { x: 0.5, y: 0.3, w: 9.0, h: 0.7, fontFace: F.head, fontSize: 28, bold: true, color: dark ? C.white : C.pine, isTextBox: true, margin: 0, valign: "middle", fit: "shrink" });
  return s;
}
function card(s, x, y, w, h, fill = C.surface, line = null) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: line ? { color: line, width: 1 } : { color: fill, width: 0 }, rectRadius: 0.08 });
}
function text(s, t, x, y, w, h, o = {}) {
  s.addText(t, Object.assign({ x, y, w, h, fontFace: F.body, fontSize: 13, color: C.ink, isTextBox: true, margin: 0.04, valign: "top", fit: "shrink" }, o));
}
function bullets(s, items, x, y, w, h, o = {}) {
  const arr = items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1 } }));
  s.addText(arr, Object.assign({ x, y, w, h, fontFace: F.body, fontSize: 13, color: C.ink, isTextBox: true, margin: 0.04, valign: "top", paraSpaceAfter: 6, fit: "shrink" }, o));
}
function chip(s, label, x, y, w, color, h = 0.38, fontSize = 12) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color }, line: { color, width: 0 }, rectRadius: 0.19 });
  s.addText(label, { x, y, w, h, fontFace: F.body, fontSize, bold: true, color: textOn(color), align: "center", valign: "middle", isTextBox: true, margin: 0 });
}
function arrow(s, x1, y, x2) {
  s.addShape(pres.shapes.LINE, { x: x1, y, w: x2 - x1, h: 0, line: { color: C.muted, width: 1.5, endArrowType: "triangle" } });
}
function regionTiles(s, x, y, w, h) {
  const regions = [["india", 650, "B8412F"], ["us-east", 400, "B9722E"], ["uk", 200, "C9A227"], ["france", 60, "6FA05A"], ["sweden", 40, "237F52"]];
  const gap = 0.08, tw = (w - gap * 4) / 5;
  regions.forEach(([name, ci, col], i) => {
    const tx = x + i * (tw + gap), tc = textOn(col);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: tx, y, w: tw, h, fill: { color: col }, line: { color: col, width: 0 }, rectRadius: 0.06 });
    s.addText(name, { x: tx, y: y + 0.08, w: tw, h: 0.3, fontFace: F.body, fontSize: 11, bold: true, color: tc, align: "center", isTextBox: true, margin: 0 });
    s.addText(String(ci), { x: tx, y: y + h - 0.64, w: tw, h: 0.36, fontFace: F.head, fontSize: 18, bold: true, color: tc, align: "center", isTextBox: true, margin: 0 });
    s.addText("gCO₂/kWh", { x: tx, y: y + h - 0.3, w: tw, h: 0.24, fontFace: F.body, fontSize: 8, color: tc, align: "center", isTextBox: true, margin: 0 });
  });
}
function readCsv(p) {
  const [head, ...rows] = fs.readFileSync(p, "utf8").trim().split(/\r?\n/);
  const cols = head.split(",");
  return rows.map((r) => Object.fromEntries(r.split(",").map((v, i) => [cols[i], v])));
}
let payback;
try { payback = readCsv(path.join(ROOT, "results", "exp01_payback_boundary.csv")); } catch (e) {
  payback = [[0.1, 0.018], [0.2, 0.035], [0.5, 0.088], [1, 0.175], [2, 0.35], [5, 0.875], [10, 1.75], [20, 3.5], [60, 10.5]].map(([s, p]) => ({ state_gb: s, payback_h: p }));
}
let policies;
try { policies = readCsv(path.join(ROOT, "results", "exp02_policy_comparison.csv")).filter((r) => r.seed === undefined || r.seed === "0"); } catch (e) {
  policies = [["carbon-unaware", 25240.8, 0.7], ["greenest-region", 11874.5, 1028.3], ["wait-only", 24861.3, 0.7], ["move-only", 12165.1, 705.5], ["migration-aware", 12003.7, 747.4], ["migration-aware-milp", 11854.6, 674.0], ["oracle-migration-aware-milp", 11896.4, 745.9]].map(([policy, exec_g, migration_g]) => ({ policy, exec_g, migration_g, resume_g: 0 }));
}
const shortName = { "carbon-unaware": "unaware", "greenest-region": "greenest", "wait-only": "wait-only", "move-only": "move-only", "migration-aware": "ours greedy", "migration-aware-milp": "ours MILP", "oracle-migration-aware-milp": "oracle" };

// 1 title
{
  const s = slideBase(null, true);
  s.addText("Carbon-Aware Autonomous Workload Orchestrator", { x: 0.6, y: 1.0, w: 8.8, h: 1.1, fontFace: F.head, fontSize: 34, bold: true, color: C.white, isTextBox: true, margin: 0, fit: "shrink" });
  s.addText("When does moving a job to a cleaner grid pay back its own carbon?", { x: 0.6, y: 2.15, w: 8.8, h: 0.5, fontFace: F.body, fontSize: 18, color: "F2B65A", isTextBox: true, margin: 0 });
  regionTiles(s, 0.6, 3.0, 4.4, 1.35);
  s.addText([
    { text: "Member 1 · Uday Kumar", options: { bold: true, breakLine: true } }, { text: "infrastructure · profiler · scheduler", options: { breakLine: true } },
    { text: "Member 2 · <name>", options: { bold: true, breakLine: true } }, { text: "carbon data · forecasting models", options: { breakLine: true } },
    { text: "Member 3 · <name>", options: { bold: true, breakLine: true } }, { text: "simulator · evaluation · replay" },
  ], { x: 5.4, y: 3.0, w: 4.0, h: 1.5, fontFace: F.body, fontSize: 11, color: "CFE0D8", isTextBox: true, margin: 0, paraSpaceAfter: 2, fit: "shrink" });
  s.addText("Mid-term evaluation · <course> · <college> · <date>", { x: 0.6, y: 4.85, w: 8.8, h: 0.35, fontFace: F.body, fontSize: 11, color: "9DB8AD", isTextBox: true, margin: 0 });
}
// 2 dirty electricity
{
  const s = slideBase("Electricity is not equally dirty");
  card(s, 0.5, 1.2, 4.3, 1.9);
  text(s, "650", 0.7, 1.25, 1.8, 0.95, { fontFace: F.head, fontSize: 52, bold: true, color: "B8412F", valign: "middle" });
  text(s, "gCO₂ per kWh · India", 2.55, 1.5, 2.2, 0.5, { fontSize: 13, color: C.muted, valign: "middle" });
  text(s, "40", 0.7, 2.25, 1.8, 0.75, { fontFace: F.head, fontSize: 36, bold: true, color: C.leaf, valign: "middle" });
  text(s, "gCO₂ per kWh · Sweden  →  16× cleaner", 2.55, 2.4, 2.2, 0.5, { fontSize: 13, color: C.muted, valign: "middle" });
  regionTiles(s, 5.2, 1.2, 4.3, 1.9);
  bullets(s, [
    "Same job, same energy, up to 16× different carbon.",
    "Carbon-aware computing: run where and when the grid is cleaner.",
    "Spatial shift = other region. Temporal shift = cleaner hour.",
  ], 0.5, 3.4, 9.0, 1.2, { fontSize: 15 });
  text(s, "Our project starts where that advice stops working.", 0.5, 4.65, 9.0, 0.45, { fontSize: 15, bold: true, color: C.pine });
}
// 3 moving is not free
{
  const s = slideBase("But moving a running job is not free");
  const steps = [["Checkpoint", "write GBs of state to disk"], ["Transfer", "copy across the network"], ["Restore", "read back, restart, job is down"]];
  steps.forEach(([h, b], i) => {
    const x = 0.5 + i * 3.1;
    card(s, x, 1.2, 2.8, 1.15);
    text(s, h, x + 0.15, 1.27, 2.5, 0.4, { fontFace: F.head, fontSize: 18, bold: true, color: C.pine });
    text(s, b, x + 0.15, 1.7, 2.5, 0.55, { fontSize: 12.5, color: C.muted });
    if (i < 2) arrow(s, x + 2.82, 1.78, x + 3.08);
  });
  text(s, "Every step costs energy. For a 60 GB job with 30 minutes left, moving emits more than staying.", 0.5, 2.5, 9.0, 0.45, { fontSize: 14, bold: true });
  card(s, 0.5, 3.1, 5.2, 2.0);
  text(s, "The gap", 0.7, 3.17, 4.8, 0.35, { fontFace: F.head, fontSize: 15, bold: true, color: C.pine });
  bullets(s, [
    "Prior work: shift in time, optimise placement, respect latency.",
    "Movement cost only on paper, or ignored.",
    "Nobody measured it on a container platform.",
  ], 0.7, 3.55, 4.85, 1.5, { fontSize: 12.5 });
  card(s, 5.9, 3.1, 3.6, 2.0, C.paleAmber, C.amber);
  text(s, "Research question", 6.1, 3.17, 3.2, 0.35, { fontFace: F.head, fontSize: 15, bold: true, color: C.pine });
  text(s, "What changes when migration carbon is measured and put inside the scheduler?", 6.1, 3.55, 3.2, 0.75, { fontSize: 12.5, bold: true });
  text(s, "H1  measured cost → less total carbon, deadlines kept\nH2  benefit depends on state size and time left", 6.1, 4.3, 3.2, 0.75, { fontSize: 11, color: C.ink });
}
// 4 payback
{
  const s = slideBase("Our answer: the Carbon Payback Period");
  card(s, 0.5, 1.2, 4.6, 1.35);
  text(s, "payback (hours) =", 0.7, 1.27, 4.2, 0.35, { fontFace: F.head, fontSize: 16, bold: true, color: C.pine });
  text(s, "migration carbon (g)", 1.6, 1.62, 3.3, 0.32, { fontSize: 14, bold: true, align: "center" });
  s.addShape(pres.shapes.LINE, { x: 1.6, y: 1.97, w: 3.3, h: 0, line: { color: C.ink, width: 1.25 } });
  text(s, "P (kW) × (CI here − CI there)", 1.6, 2.0, 3.3, 0.32, { fontSize: 13, align: "center" });
  text(s, "MOVE only if remaining runtime > payback", 0.7, 2.28, 4.2, 0.28, { fontSize: 12.5, bold: true, color: C.leaf });
  const cell = (t, o = {}) => ({ text: t, options: Object.assign({ fontFace: F.body, fontSize: 10, color: C.ink, align: "center", valign: "middle" }, o) });
  const hdr = (t) => cell(t, { bold: true, fill: { color: C.surface }, color: C.pine });
  s.addTable([
    [hdr("job"), hdr("state"), hdr("time left"), hdr("saves"), hdr("move costs"), hdr("payback"), hdr("decision")],
    [cell("A", { bold: true }), cell("0.2 GB"), cell("2 h"), cell("240 g"), cell("4 g"), cell("2 min"), cell("MOVE", { bold: true, color: C.white, fill: { color: C.move } })],
    [cell("B", { bold: true }), cell("60 GB"), cell("0.5 h"), cell("60 g"), cell("1260 g"), cell("10.5 h"), cell("REFUSE", { bold: true, color: C.white, fill: { color: C.refuse } })],
  ], { x: 0.5, y: 2.75, w: 4.6, colW: [0.5, 0.65, 0.7, 0.6, 0.85, 0.65, 0.65], rowH: 0.34, border: { type: "solid", color: C.line, pt: 0.75 } });
  text(s, "Same regions (India → Sweden), same 200 W job. Only state size and time left differ.", 0.5, 3.9, 4.6, 0.6, { fontSize: 11, color: C.muted });
  s.addChart(pres.charts.LINE, [{ name: "payback hours", labels: payback.map((r) => String(+r.state_gb)), values: payback.map((r) => +(+r.payback_h).toFixed(2)) }], {
    x: 5.3, y: 1.2, w: 4.2, h: 3.5, chartColors: [C.teal], lineSize: 2, lineDataSymbol: "circle", lineDataSymbolSize: 6,
    showTitle: true, title: "Minimum remaining hours for MOVE vs state size (GB)", titleFontSize: 10, titleColor: C.ink, titleFontFace: F.body,
    showLegend: false, showValue: true, dataLabelPosition: "t", dataLabelFontSize: 8, dataLabelColor: C.muted, dataLabelFormatCode: "0.0#",
    catAxisLabelFontSize: 9, valAxisLabelFontSize: 9, catAxisLabelColor: C.muted, valAxisLabelColor: C.muted,
    valGridLine: { color: "E3E8E5", size: 0.5 }, catGridLine: { style: "none" }, showCatAxisTitle: true, catAxisTitle: "state size (GB)", catAxisTitleFontSize: 9, catAxisTitleColor: C.muted,
    showValAxisTitle: true, valAxisTitle: "hours", valAxisTitleFontSize: 9, valAxisTitleColor: C.muted, valAxisMinVal: 0,
  });
  text(s, "0.2 kW job, 650 → 50 gCO₂/kWh, 0.06 kWh per GB. Placeholder constants until the profiler run.", 5.3, 4.75, 4.2, 0.4, { fontSize: 9.5, color: C.muted });
}
// 5 system
{
  const s = slideBase("System at a glance");
  const boxes = [["Carbon data", "UK ESO · ENTSO-E\nEIA · Electricity Maps"], ["Forecaster", "next 24 h of CI\nper region"], ["Decision engine", "payback · WAIT\nSLA · MILP"], ["Kubernetes testbed", "k3d, 5 nodes = 5 regions\nreal CI replayed"], ["Telemetry", "SQLite → experiments\n→ replay"]];
  boxes.forEach(([h, b], i) => {
    const x = 0.5 + i * 1.86, w = 1.7;
    card(s, x, 1.25, w, 1.25, i === 2 ? C.pine : C.surface);
    text(s, h, x + 0.08, 1.31, w - 0.16, 0.4, { fontFace: F.head, fontSize: 13, bold: true, color: i === 2 ? C.white : C.pine, align: "center" });
    text(s, b, x + 0.08, 1.71, w - 0.16, 0.75, { fontSize: 10, color: i === 2 ? "CFE0D8" : C.muted, align: "center" });
    if (i < 4) arrow(s, x + w + 0.01, 1.87, x + w + 0.15);
  });
  card(s, 3.05, 2.95, 3.9, 0.85, C.paleAmber, C.amber);
  text(s, "Migration cost model", 3.2, 3.0, 3.6, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine, align: "center" });
  text(s, "energy = a × GB + b per phase, measured by the profiler · network kWh/GB", 3.2, 3.33, 3.6, 0.45, { fontSize: 10, align: "center" });
  s.addShape(pres.shapes.LINE, { x: 5.0, y: 2.95, w: 0, h: -0.43, line: { color: C.amber, width: 1.5, endArrowType: "triangle" } });
  text(s, "Every hour, for every job, one word:", 0.5, 4.0, 9.0, 0.35, { fontSize: 13, bold: true });
  const acts = [["MOVE", C.move, "payback met"], ["WAIT", C.wait, "cleaner hour coming"], ["HOLD", C.hold, "no greener allowed region"], ["REFUSE", C.refuse, "greener exists, no payback"]];
  acts.forEach(([a, col, d], i) => { const x = 0.5 + i * 2.3; chip(s, a, x, 4.4, 1.05, col); text(s, d, x + 1.12, 4.38, 1.2, 0.5, { fontSize: 9.5, color: C.muted }); });
}
// 6 tech stack
{
  const s = slideBase("Tech stack");
  const rows = [
    ["Language", "Python 3.10+", "one language, data to cluster"],
    ["Data", "pandas · NumPy", "hourly time series"],
    ["Machine learning", "scikit-learn · XGBoost", "small tabular data → gradient boosting"],
    ["Optimisation", "PuLP + CBC", "open-source MILP, 0.4 s per 24 h plan"],
    ["Energy", "psutil · RAPL · Kepler", "joules per phase, hardware or model"],
    ["Platform", "Docker · k3d Kubernetes", "real scheduler, 5 regions on one laptop"],
    ["Storage", "SQLite · CSV", "zero setup, reproducible"],
    ["Visualisation", "matplotlib · HTML/SVG replay · Streamlit", "figures, offline demo, dashboard"],
    ["Quality", "pytest (44) · ruff · GitHub", "every experiment = one command"],
  ];
  const cell = (t, o = {}) => ({ text: t, options: Object.assign({ fontFace: F.body, fontSize: 11, color: C.ink, valign: "middle" }, o) });
  const H = (t) => cell(t, { bold: true, color: C.pine, fill: { color: C.surface } });
  s.addTable([[H("layer"), H("tools"), H("why")], ...rows.map(([a, b, c]) => [cell(a, { bold: true }), cell(b, { color: C.teal, bold: true }), cell(c, { color: C.muted })])],
    { x: 0.5, y: 1.2, w: 9.0, colW: [1.7, 3.3, 4.0], rowH: 0.4, border: { type: "solid", color: C.line, pt: 0.75 } });
}
// 7 data
{
  const s = slideBase("Data: real grid carbon intensity");
  const cell = (t, o = {}) => ({ text: t, options: Object.assign({ fontFace: F.body, fontSize: 11, color: C.ink, valign: "middle" }, o) });
  const H = (t) => cell(t, { bold: true, color: C.pine, fill: { color: C.surface } });
  s.addTable([
    [H("region"), H("source"), H("CI obtained")],
    [cell("uk", { bold: true }), cell("UK National Grid ESO"), cell("published, no key")],
    [cell("sweden · france", { bold: true }), cell("ENTSO-E"), cell("fuel mix × IPCC factors")],
    [cell("us-east (PJM)", { bold: true }), cell("US EIA"), cell("fuel mix × IPCC factors")],
    [cell("india (IN-WE)", { bold: true }), cell("Electricity Maps"), cell("24 h per call, collected daily")],
  ], { x: 0.5, y: 1.2, w: 5.6, colW: [1.4, 2.0, 2.2], rowH: 0.42, border: { type: "solid", color: C.line, pt: 0.75 } });
  card(s, 6.4, 1.2, 3.1, 2.1);
  text(s, "One schema", 6.55, 1.27, 2.8, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine });
  text(s, "timestamp  (UTC, hourly)\nregion\nci_g_per_kwh\nsource", 6.55, 1.65, 2.8, 1.0, { fontFace: "Courier New", fontSize: 11 });
  text(s, "gaps ≤ 3 h interpolated · SQLite + CSV", 6.55, 2.7, 2.8, 0.45, { fontSize: 10, color: C.muted });
  bullets(s, [
    "IPCC lifecycle factors: coal 820 · gas 490 · nuclear 12 · hydro 24 · wind 11 · solar 45 gCO₂/kWh",
    "Real traces because the payback boundary depends on the CI gap and its daily shape",
    "Synthetic traces only for offline development, always labelled, never reported",
  ], 0.5, 3.55, 9.0, 1.5, { fontSize: 12.5 });
}
// 8 models
{
  const s = slideBase("Models: now, and planned for the final");
  const col = (x, title, tint, chipCol, items) => {
    card(s, x, 1.2, 4.4, 3.4, tint);
    text(s, title, x + 0.15, 1.25, 4.1, 0.35, { fontFace: F.head, fontSize: 14, bold: true, color: C.pine });
    items.forEach(([n, h, what, why], i) => {
      const y = 1.65 + i * 0.97;
      chip(s, n, x + 0.15, y + 0.02, 0.34, chipCol, 0.34, 11);
      text(s, h, x + 0.58, y, 3.7, 0.3, { fontSize: 12.5, bold: true });
      text(s, what, x + 0.58, y + 0.29, 3.7, 0.3, { fontSize: 10.5 });
      text(s, why, x + 0.58, y + 0.57, 3.7, 0.36, { fontSize: 10.5, color: C.muted, italic: true });
    });
  };
  col(0.5, "In place now", C.surface, C.leaf, [
    ["1", "24 h carbon-intensity forecaster", "gradient boosting on lags, hour, weekday", "why: small tabular data, beats naive baselines"],
    ["2", "Migration cost model", "linear fit per phase: energy = a × GB + b", "why: measured constants, R² reported"],
    ["3", "Placement optimiser (MILP)", "joint 24 h plan: residence, execution, movement", "why: exact reference for the payback rule"],
  ]);
  col(5.1, "After mid-term → final", C.paleAmber, C.amber, [
    ["4", "Probabilistic forecaster", "quantile boosting (P10/P50/P90) + LSTM baseline", "why: decide WAIT / MOVE on the pessimistic case"],
    ["5", "Remaining-runtime predictor", "regression on early training progress", "why: payback needs 'time left'"],
    ["6", "Learned migration cost model", "boosting on size, compressibility, bandwidth, RTT", "why: linear model ignores network conditions"],
  ]);
  card(s, 0.5, 4.72, 9.0, 0.5, C.pine);
  text(s, "Models predict the inputs. The payback rule stays transparent.", 0.7, 4.75, 8.6, 0.44, { fontSize: 12.5, bold: true, color: C.white, valign: "middle", align: "center" });
}
// 9 decision engine
{
  const s = slideBase("Decision engine: four words, every hour, per job");
  const acts = [["MOVE", C.move, "Migrate now.", "Saving over remaining runtime > migration carbon."], ["WAIT", C.wait, "Not yet.", "A cleaner hour comes before the deadline."], ["HOLD", C.hold, "Stay.", "No cleaner region is allowed (SLA, capacity)."], ["REFUSE", C.refuse, "Stay, on purpose.", "Cleaner region exists, move does not pay back."]];
  acts.forEach(([a, col, h, d], i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.2, 2.15, 2.0);
    chip(s, a, x + 0.15, 1.35, 1.1, col, 0.4, 13);
    text(s, h, x + 0.15, 1.85, 1.85, 0.35, { fontSize: 13, bold: true });
    text(s, d, x + 0.15, 2.2, 1.85, 0.95, { fontSize: 11, color: C.muted });
  });
  card(s, 0.5, 3.4, 4.4, 1.75, C.white, C.line);
  text(s, "Hard latency rule", 0.65, 3.47, 4.1, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine });
  text(s, "A web service for Indian users runs only where round-trip ≤ its SLA. Sweden at 150 ms is out, however clean.", 0.65, 3.85, 4.1, 1.2, { fontSize: 12 });
  card(s, 5.1, 3.4, 4.4, 1.75, C.white, C.line);
  text(s, "Two engines, same words", 5.25, 3.47, 4.1, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine });
  text(s, "Greedy: instant, explainable.\nMILP: joint 24 h plan with movement cost, pause cost, capacity; 0.4 s per tick.", 5.25, 3.85, 4.1, 1.2, { fontSize: 12 });
}
// 10 evaluation
{
  const s = slideBase("Evaluation: same jobs, same data, true costs charged to all");
  card(s, 0.5, 1.2, 4.4, 2.6);
  text(s, "Policies", 0.65, 1.25, 4.1, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine });
  bullets(s, ["carbon-unaware: run in place", "greenest-region: chase the cleanest grid, cost ignored", "wait-only: shift in time only", "move-only: payback-aware, never waits", "ours: payback + WAIT + SLA (greedy, MILP)", "oracle: ours with perfect forecasts"], 0.65, 1.6, 4.15, 2.15, { fontSize: 11.5 });
  card(s, 5.1, 1.2, 4.4, 1.15);
  text(s, "Metrics", 5.25, 1.25, 4.1, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine });
  text(s, "total gCO₂e · migrations · deadline misses · SLA-violation hours · regret vs oracle · payback boundary", 5.25, 1.6, 4.1, 0.7, { fontSize: 11 });
  card(s, 5.1, 2.5, 4.4, 1.3);
  text(s, "Experiments", 5.25, 2.55, 4.1, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine });
  text(s, "EXP-01 payback boundary (H2) · EXP-02 policies on real traces (H1) · EXP-03 forecast error → regret · EXP-04 network kWh/GB sensitivity · EXP-05 replay · EXP-06 live migrations vs model", 5.25, 2.9, 4.1, 0.85, { fontSize: 10.5 });
  card(s, 0.5, 3.95, 9.0, 1.2, C.paleAmber);
  text(s, "Testbed", 0.65, 4.0, 1.2, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine });
  text(s, "k3d Kubernetes on one laptop, five nodes labelled as regions, each replaying real CI. Workloads: ML training, batch, web service. Controller patches the node selector; the job checkpoints on SIGTERM and restores on the target node. Downtime measured.", 1.85, 4.0, 7.5, 1.1, { fontSize: 11 });
}
// 11 status
{
  const s = slideBase("Where we are at mid-term");
  card(s, 0.5, 1.2, 3.6, 3.95);
  text(s, "Built and tested", 0.65, 1.25, 3.3, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine });
  bullets(s, ["End-to-end pipeline runs", "44 automated tests", "Greedy engine + MILP (0.4 s / plan)", "Simulator: 6 policies + oracle", "Profiler + cost-model fitting", "Controller, k3d scripts, 3 workload images", "Replay page + GIF"], 0.65, 1.6, 3.35, 2.4, { fontSize: 11.5 });
  text(s, "Next: profiler on the Linux testbed, real CI for 5 regions, live migrations.", 0.65, 4.2, 3.3, 0.85, { fontSize: 11, color: C.muted, italic: true });
  s.addChart(pres.charts.BAR, [
    { name: "execution", labels: policies.map((r) => shortName[r.policy] || r.policy), values: policies.map((r) => Math.round(+r.exec_g)) },
    { name: "migration + restart", labels: policies.map((r) => shortName[r.policy] || r.policy), values: policies.map((r) => Math.round(+r.migration_g + +(r.resume_g || 0))) },
  ], {
    x: 4.3, y: 1.2, w: 5.2, h: 3.35, barDir: "col", barGrouping: "stacked", chartColors: [C.teal, C.amber], barGapWidthPct: 60,
    showTitle: true, title: "Total gCO₂e per policy · 7 days × 20 jobs", titleFontSize: 11, titleColor: C.ink, titleFontFace: F.body,
    showLegend: true, legendPos: "b", legendFontSize: 9, legendColor: C.muted, showValue: false,
    catAxisLabelFontSize: 8.5, valAxisLabelFontSize: 8.5, catAxisLabelColor: C.muted, valAxisLabelColor: C.muted,
    valGridLine: { color: "E3E8E5", size: 0.5 }, catGridLine: { style: "none" }, valAxisMinVal: 0, valAxisLabelFormatCode: "#,##0",
  });
  card(s, 4.3, 4.62, 5.2, 0.53, C.paleAmber, C.amber);
  text(s, "Synthetic traces, placeholder constants: pipeline check, not a result.", 4.4, 4.65, 5.0, 0.48, { fontSize: 10.5, bold: true, color: C.pine, valign: "middle" });
}
// 12 demo
{
  const s = slideBase("Demo: the replay");
  s.addImage({ path: path.join(HERE, "img", "replay-page.png"), x: 0.5, y: 1.2, w: 5.4, h: 3.95, sizing: { type: "contain", w: 5.4, h: 3.95 } });
  card(s, 6.15, 1.2, 3.35, 3.95, C.surface);
  text(s, "What you see", 6.3, 1.25, 3.05, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine });
  bullets(s, ["Region columns coloured by live CI", "Dots = jobs, ring = progress", "Arrow on MOVE, yellow ring WAIT, red ring REFUSE", "Carbon totals of all policies, side by side", "Decision log with payback hours", "Self-contained HTML, no server"], 6.3, 1.6, 3.1, 3.4, { fontSize: 11.5 });
}
// 13 road to final
{
  const s = slideBase("Road to the final evaluation");
  const steps = [["1", "Measure", "profiler on Linux testbed\n0.1–20 GB × 3 → fitted constants"], ["2", "Real data", "60+ days of CI, 5 regions\nforecaster trained + backtested"], ["3", "Learn", "probabilistic forecaster\nruntime predictor · learned cost"], ["4", "Prove", "EXP-01…04 on real data, 5 seeds\n≥ 10 live migrations vs model"]];
  steps.forEach(([n, h, b], i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.2, 2.15, 1.95);
    chip(s, n, x + 0.15, 1.35, 0.4, C.leaf, 0.4, 13);
    text(s, h, x + 0.65, 1.37, 1.4, 0.38, { fontFace: F.head, fontSize: 15, bold: true, color: C.pine });
    text(s, b, x + 0.15, 1.9, 1.85, 1.15, { fontSize: 11 });
    if (i < 3) arrow(s, x + 2.17, 2.15, x + 2.28);
  });
  text(s, "Risks we plan for", 0.5, 3.4, 9.0, 0.35, { fontFace: F.head, fontSize: 13, bold: true, color: C.pine });
  const risks = [["Network energy per GB spans 10× in the literature", "sensitivity study is a headline result"], ["No hardware energy counters on laptops", "wall-plug meter calibration, method reported"], ["No official real-time carbon feed for India", "daily collection from now, labelled fallback"]];
  risks.forEach(([r, m], i) => { const y = 3.8 + i * 0.45; text(s, r, 0.5, y, 4.6, 0.4, { fontSize: 11.5 }); arrow(s, 5.15, y + 0.17, 5.4); text(s, m, 5.5, y, 4.0, 0.4, { fontSize: 11.5, color: C.leaf }); });
}
// 14 closing
{
  const s = slideBase(null, true);
  s.addText("Move only when the move pays back.", { x: 0.6, y: 1.3, w: 8.8, h: 1.0, fontFace: F.head, fontSize: 34, bold: true, color: C.white, isTextBox: true, margin: 0, fit: "shrink" });
  s.addText("Measured migration cost · real grid carbon · one transparent rule · real Kubernetes.", { x: 0.6, y: 2.3, w: 8.8, h: 0.5, fontFace: F.body, fontSize: 16, color: "F2B65A", isTextBox: true, margin: 0 });
  [["MOVE", C.move], ["WAIT", C.wait], ["HOLD", C.hold], ["REFUSE", C.refuse]].forEach(([a, col], i) => chip(s, a, 0.6 + i * 1.3, 3.1, 1.15, col, 0.42, 13));
  s.addText("github.com/Uday2k5/Carbon-aware-orchestrator", { x: 0.6, y: 4.0, w: 8.8, h: 0.4, fontFace: "Courier New", fontSize: 13, color: "CFE0D8", isTextBox: true, margin: 0 });
  s.addText("Questions?", { x: 0.6, y: 4.5, w: 8.8, h: 0.6, fontFace: F.head, fontSize: 24, bold: true, color: C.white, isTextBox: true, margin: 0 });
}

pres.writeFile({ fileName: OUT }).then(() => console.log(`wrote ${OUT}`));
