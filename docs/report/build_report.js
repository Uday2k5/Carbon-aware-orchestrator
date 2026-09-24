// Builds docs/report/Carbon-Aware-Orchestrator-Report.docx with docx-js.
//   npm install docx   (once)      node docs/report/build_report.js
const fs = require("fs");
const path = require("path");
const D = require("docx");
const { Document, Packer, Paragraph, TextRun, AlignmentType, PageBreak, ImageRun, Header, PageNumber,
  LevelFormat, Table, TableRow, TableCell, WidthType, BorderStyle, TabStopType, LeaderType } = D;

const HERE = __dirname;
const OUT = path.join(HERE, "Carbon-Aware-Orchestrator-Report.docx");
const FONT = "Arial";
const BODY = 22;   // half-points: 11 pt
const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder, insideHorizontal: noBorder, insideVertical: noBorder };

function pngSize(buf) { return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) }; }
const run = (t, o = {}) => new TextRun(Object.assign({ text: t, font: FONT, size: BODY }, o));
const para = (t, o = {}, ro = {}) => new Paragraph(Object.assign({ children: [run(t, ro)], spacing: { after: 120, line: 300 } }, o));
const heading = (t) => new Paragraph({ children: [run(t, { bold: true, size: 32 })], spacing: { after: 240 }, keepNext: true });
const sub = (t) => new Paragraph({ children: [run(t, { bold: true, size: 24 })], spacing: { before: 160, after: 80 }, keepNext: true });
const body = (t) => para(t, { alignment: AlignmentType.JUSTIFIED });
const mixed = (parts, o = {}) => new Paragraph(Object.assign({ children: parts.map(([t, b]) => run(t, b ? { bold: true } : {})), spacing: { after: 120, line: 300 }, alignment: AlignmentType.JUSTIFIED }, o));
const bullet = (lead, t) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 100, line: 300 }, alignment: AlignmentType.JUSTIFIED,
  children: lead ? [run(lead, { bold: true }), run(t)] : [run(t)] });
const blank = () => new Paragraph({ children: [run("")], spacing: { after: 0 } });
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });
const center = (t, size, bold = true, after = 120) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after }, children: [run(t, { size, bold })] });

const children = [];

// ---------------------------------------------------------------- title page
const logo = fs.readFileSync(path.join(HERE, "img", "logo.png"));
const ls = pngSize(logo);
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
  children: [new ImageRun({ type: "png", data: logo, transformation: { width: 96, height: Math.round(96 * ls.h / ls.w) } })] }));
children.push(center("JAYPEE INSTITUTE OF INFORMATION TECHNOLOGY, NOIDA", 30));
children.push(center("B. TECH VII SEMESTER", 26, true, 60));
children.push(center("ODD SEMESTER 2026", 26, true, 600));
children.push(center("<PROJECT COURSE NAME> [<COURSE CODE>]", 26, true, 120));
children.push(center("Carbon-Aware Autonomous Workload Orchestrator", 36, true, 700));
const cellP = (t, b = false) => new Paragraph({ spacing: { after: 60 }, children: [run(t, b ? { bold: true } : {})] });
const tcell = (paras, w) => new TableCell({ width: { size: w, type: WidthType.DXA }, borders: noBorders, children: paras });
children.push(new Table({ width: { size: 9000, type: WidthType.DXA }, columnWidths: [4500, 4500], borders: noBorders, rows: [
  new TableRow({ children: [
    tcell([cellP("Submitted by:", true), cellP("Uday Kumar (23103064)"), cellP("<Member 2 name> (<enrolment no.>)"), cellP("<Member 3 name> (<enrolment no.>)")], 4500),
    tcell([cellP("Submitted to:", true), cellP("<Faculty name>"), cellP("<Faculty name>")], 4500),
  ] }),
]}));
children.push(blank());
children.push(cellP("Supervision of:", true));
children.push(cellP("<Supervisor name>"));
children.push(pageBreak());

// ---------------------------------------------------------------- index
children.push(new Paragraph({ children: [run("Index:", { bold: true, size: 28 })], spacing: { after: 240 } }));
const index = [["1. Introduction", 3], ["2. Objectives and Approach", 4], ["3. Literature Review", 5], ["4. Dataset", 6], ["5. Project Flow", 8],
  ["6. Model Performance and Evaluation Metrics", 11], ["7. Future Work", 13], ["8. Conclusion", 14], ["9. References", 15]];
for (const [t, p] of index) {
  children.push(new Paragraph({ tabStops: [{ type: TabStopType.RIGHT, position: 9000, leader: LeaderType.DOT }], spacing: { after: 200, line: 320 },
    children: [run(t, { size: 24 }), run(`\t${p}`, { size: 24 })] }));
}
children.push(pageBreak());

// ---------------------------------------------------------------- 1 introduction (p3)
children.push(heading("Introduction"));
children.push(body("The carbon emitted per kilowatt-hour of electricity differs by more than an order of magnitude between regions and between hours of the day. Carbon-aware computing exploits this by shifting flexible workloads to cleaner times or cleaner locations. Moving a running workload, however, is not free: its state must be checkpointed, transferred across a network and restored, and each step consumes energy and causes downtime. Existing carbon-aware schedulers either ignore this cost or model it only on paper. The Carbon-Aware Autonomous Workload Orchestrator is a Kubernetes control plane that measures the carbon cost of migration and moves a workload only when the carbon it saves over its remaining runtime exceeds the carbon the move itself emits."));
children.push(body("The project implements a complete pipeline comprising three integrated components:"));
children.push(bullet("A Measurement and Cost-Modelling Layer: ", "a migration profiler that measures checkpoint, transfer and restore time and energy for state sizes from 0.1 to 20 GB and fits a linear cost model."));
children.push(bullet("A Decision Engine: ", "a payback test, temporal shifting, a hard latency constraint and a mixed-integer linear programme (MILP) that plans placement jointly over a 24-hour forecast, producing one of four actions per workload: MOVE, WAIT, HOLD or REFUSE."));
children.push(bullet("A Kubernetes Testbed and Evaluation Suite: ", "a k3d cluster whose nodes emulate five grid regions replaying real carbon-intensity traces, a controller that performs cooperative checkpoint-and-reschedule migrations, and a simulator that compares the proposed policy against five baselines and an oracle."));
children.push(body("This work demonstrates that a simple, transparent rule, the Carbon Payback Period, prevents the wasteful migrations of cost-blind carbon-aware scheduling while retaining most of its benefit."));
children.push(pageBreak());

// ---------------------------------------------------------------- 2 objectives (p4)
children.push(heading("Objectives and Approach"));
children.push(mixed([["Problem Statement: ", true], ["The challenge is to decide, at every scheduling interval, whether a running or pending workload should execute where it is, move to a region with cleaner electricity, or wait for a cleaner hour, when moving itself costs energy and time. Conventional carbon-aware policies chase the region with the lowest carbon intensity and migrate repeatedly; for workloads with large state and little remaining runtime this emits more carbon than doing nothing. The goal is a scheduler that treats migration carbon as a measured quantity, respects deadlines and latency agreements, and can explain every decision.", false]]));
children.push(mixed([["Proposed Solution: ", true], ["The proposed solution is an end-to-end orchestrator that ingests grid carbon data, forecasts it and outputs explainable placement decisions.", false]]));
children.push(bullet("Carbon Payback Period: ", "for a workload of power P at a region with carbon intensity CI_src and a candidate region CI_dst, the saving rate is P × (CI_src − CI_dst) grams per hour. The payback period is the migration carbon divided by this rate; a move is issued only when the remaining runtime exceeds it."));
children.push(bullet("Measured Migration Cost: ", "a profiler executes checkpoint, transfer and restore for increasing state sizes S and fits E = a·S + b per phase. Network transfer energy is modelled as S × kWh/GB with a literature parameter."));
children.push(bullet("Decision Engine: ", "a greedy engine applies the payback test, the cheapest start window before the deadline (WAIT) and a round-trip-time constraint for web services. A MILP solved with CBC plans all workloads jointly over 24 hours as the exact reference."));
children.push(bullet("Kubernetes Controller and Evaluation: ", "the controller reads workload annotations, queries the engine and applies MOVE by patching the Deployment's node selector; the workload checkpoints on SIGTERM and restores on the target node. A simulator charges every policy the true execution, migration and restart carbon."));
children.push(pageBreak());

// ---------------------------------------------------------------- 3 literature (p5)
children.push(heading("Literature Review"));
children.push(body("Carbon-aware computing was established at production scale by Google's Carbon-Intelligent Computing System, which shifts flexible datacentre load towards hours of lower grid carbon intensity. Wiesner et al. (Let's Wait Awhile) quantified temporal shifting for Germany, Great Britain, France and California and showed that the achievable reduction depends strongly on workload flexibility and forecast accuracy. Hanafy et al. (CarbonScaler) implemented carbon-aware elasticity on Kubernetes, scaling batch and machine-learning jobs with the carbon signal. Souza et al. (CASPER) balanced carbon intensity against network latency for web services under service-level objectives, and Ecovisor exposed energy and carbon telemetry to applications. Lechowicz et al. (CarbonClipper) formalised spatiotemporal workload management as an online optimisation problem in which movement between locations incurs a cost."));
children.push(body("A second line of work concerns the cost of moving computation. Clark et al. demonstrated that live migration of virtual machines carries measurable overheads in transferred state and downtime, governed by the workload's writable working set. Estimates of the electricity intensity of Internet data transmission (Aslan et al.) span an order of magnitude. Together these works motivate the present project: movement cost has been modelled theoretically, but not measured on a container platform and integrated into a carbon-aware controller."));
children.push(pageBreak());

// ---------------------------------------------------------------- 4 dataset (p6-7)
children.push(heading("Dataset"));
children.push(body("Two kinds of data are used: grid carbon-intensity time series from authoritative grid operators, and migration measurements produced on the project's own testbed. Grid data are collected for the five regions emulated by the five nodes of the Kubernetes cluster."));
children.push(sub("Study Regions:"));
children.push(body("India (western grid), Sweden (bidding zone SE3), France, US-East (PJM interconnection) and Great Britain. The regions span carbon intensities from roughly 40 to 700 gCO₂e/kWh and different daily patterns driven by hydro, nuclear, coal and wind generation."));
children.push(sub("Grid Carbon-Intensity Dataset:"));
children.push(body("Source: UK National Grid ESO Carbon Intensity API (Great Britain), ENTSO-E Transparency Platform (Sweden, France), US Energy Information Administration (PJM) and Electricity Maps (India)."));
children.push(body("Duration: hourly, at least 60 days per region; the Great Britain series is available from 2018."));
children.push(body("Attributes used: Timestamp (UTC), Region, Carbon intensity (gCO₂e/kWh), Source."));
children.push(body("Usage: replayed on the cluster nodes, forecaster training and simulation."));
children.push(pageBreak());
children.push(sub("Migration Measurement Dataset:"));
children.push(body("Source: the project's migration profiler executed on the Linux testbed."));
children.push(body("Design: state sizes of 0.1, 0.5, 1, 5, 10 and 20 GB with three repeats each; loopback TCP transfer, optionally shaped with tc netem."));
children.push(body("Attributes used: State size, Checkpoint time and energy, Transfer time and energy, Bytes transferred, Restore time and energy, Energy method."));
children.push(body("Usage: least-squares fit of E = a·S + b per phase and of downtime d(S) for the migration cost model."));
children.push(sub("Workload Dataset:"));
children.push(body("Three workload classes are generated with seeded parameters: machine-learning training (4–12 h, 0.5–20 GB state, deadline slack), batch processing (1–4 h, 0.1–5 GB) and always-on web services with a round-trip-time SLA and a user region."));
children.push(sub("Pre-processing and Structuring:"));
children.push(body("Generation-per-fuel series from ENTSO-E and EIA are converted to carbon intensity with IPCC AR5 lifecycle emission factors (coal 820, gas 490, nuclear 12, hydro 24, wind 11, solar 45 gCO₂e/kWh). All series are resampled to hourly UTC means, gaps of up to three hours are interpolated, and the result is stored as one table in SQLite and CSV. Synthetic traces with the same schema exist for offline development; they are labelled and never reported as findings."));
children.push(pageBreak());

// ---------------------------------------------------------------- 5 project flow (p8-9) + figure (p10)
children.push(heading("Project Flow"));
children.push(sub("1. Carbon Data Acquisition and Normalisation"));
children.push(body("The pipeline begins with scheduled retrieval of hourly carbon-intensity data from the UK ESO API, ENTSO-E, EIA and Electricity Maps. Generation mixes are converted to gCO₂e/kWh with IPCC lifecycle factors, resampled to hourly UTC values and written to a single normalised table."));
children.push(sub("2. Carbon-Intensity Forecasting"));
children.push(body("For each region a direct multi-horizon gradient-boosting model predicts the next 24 hours from lagged values, rolling statistics and calendar features. Persistence and seasonal-naive forecasters serve as baselines, and the residual spread per horizon provides prediction intervals. A rolling-origin backtest reports MAE and MAPE per horizon step."));
children.push(sub("3. Migration Profiling and Cost Modelling"));
children.push(body("The profiler checkpoints a synthetic state of a given size to disk, transfers it over a loopback TCP connection and restores it, measuring wall time and energy for each phase with hardware counters or a utilisation-based power model. A straight line E = a·S + b is fitted per phase with R² reported, and combined with network energy and downtime into the migration cost model."));
children.push(pageBreak());
children.push(sub("4. Decision Engine Development"));
children.push(body("The engine filters candidate regions by the latency SLA, evaluates the payback test for a running workload and the cheapest start window for a deferrable one, and emits MOVE, WAIT, HOLD or REFUSE with the saved carbon, migration carbon and payback period recorded in the reason. A MILP over the forecast horizon models state residence, execution, movement, pause cost, capacity and contiguity, and is decoded into the same four actions."));
children.push(sub("5. Kubernetes Controller and Testbed Integration"));
children.push(body("A k3d cluster is created with five agent nodes labelled as regions and a shared checkpoint volume. Three workload containers (training, batch, web service) checkpoint on SIGTERM and restore on start. The controller lists managed pods, builds workload descriptions from annotations, calls the engine and applies MOVE by patching the Deployment's node selector; downtime and checkpoint time are recorded in SQLite."));
children.push(sub("6. Simulation, Evaluation and Documentation"));
children.push(body("The simulator replays the traces hour by hour for identical job sets under each policy and charges the true execution, migration and restart carbon. Experiments produce the payback boundary, the policy comparison, the forecast-error sensitivity and the network-energy sensitivity, and a self-contained replay page and animation visualise every decision. Results and the fitted constants are compiled into this report."));
children.push(pageBreak());
const flow = fs.readFileSync(path.join(HERE, "img", "flow.png"));
const fsz = pngSize(flow);
const fw = 540, fh = Math.round(fw * fsz.h / fsz.w);
children.push(new Paragraph({ alignment: AlignmentType.CENTER, children: [new ImageRun({ type: "png", data: flow, transformation: { width: fw, height: Math.min(fh, 780) } })] }));
children.push(pageBreak());

// ---------------------------------------------------------------- 6 evaluation (p11-12)
children.push(heading("Model Performance and Evaluation Metrics"));
children.push(body("The orchestrator is evaluated with a quantitative framework that separates the quality of its models from the carbon outcome of its decisions."));
children.push(sub("I. Carbon-Intensity Forecasting (Gradient Boosting)"));
children.push(bullet("Mean Absolute Error (MAE) and Mean Absolute Percentage Error (MAPE): ", "per horizon step from a rolling-origin backtest, compared against persistence and seasonal-naive baselines."));
children.push(bullet("Interval Coverage: ", "the share of observed values inside the P10–P90 band produced from the residual spread."));
children.push(bullet("Downstream Regret: ", "the additional carbon emitted when the scheduler uses the forecast instead of perfect knowledge."));
children.push(sub("II. Migration Cost Model (Linear Regression)"));
children.push(bullet("Coefficient of Determination (R²): ", "per phase for E = a·S + b, with a target of R² ≥ 0.9 from at least six state sizes and three repeats."));
children.push(bullet("Prediction Error: ", "of downtime and energy against live controller migrations on the cluster."));
children.push(pageBreak());
children.push(sub("III. Scheduler and System Utility"));
children.push(bullet("Total Lifecycle Carbon (gCO₂e): ", "execution, migration and restart, compared across carbon-unaware, greenest-region, wait-only, move-only, the proposed greedy and MILP policies and an oracle with perfect forecasts."));
children.push(bullet("Constraint Compliance: ", "number of migrations, deadline violations and SLA-violation hours, which must not exceed those of the baselines."));
children.push(bullet("Regret and Payback Boundary: ", "regret against the oracle, and the minimum remaining runtime for MOVE as a function of state size and carbon-intensity gap."));
children.push(bullet("Solver Latency: ", "a dense 24-hour MILP with 20 workloads and 5 regions is planned in about 0.4 s."));
children.push(body("Preliminary results on synthetic traces with placeholder constants serve as a pipeline check only: over a simulated week with 20 workloads, the payback-aware policies emitted about 50% less carbon than carbon-unaware placement and 1–3% less than greenest-region placement while performing 43–55% fewer migrations, with no SLA violations. Measured constants and real traces replace these figures in the final evaluation."));
children.push(pageBreak());

// ---------------------------------------------------------------- 7 future work (p13)
children.push(heading("Future Work"));
children.push(body("To move from a validated prototype to a complete research result, the following extensions are planned."));
children.push(bullet("Probabilistic Forecasting: ", "quantile gradient boosting and an LSTM baseline will provide P10/P50/P90 forecasts so that WAIT and MOVE decisions are taken on the pessimistic quantile rather than the point estimate."));
children.push(bullet("Remaining-Runtime Prediction: ", "a regression model on early training progress (steps per second, loss slope, epoch count) will estimate the remaining runtime of machine-learning jobs."));
children.push(bullet("Learned Migration Cost Model: ", "gradient boosting on state size, compressibility, bandwidth and round-trip time, collected under traffic shaping, will replace the linear model where network conditions vary."));
children.push(bullet("Live Cluster Validation: ", "at least ten controller-driven migrations on the k3d testbed will be compared against the model's predicted downtime and energy."));
children.push(bullet("Later Directions: ", "carbon-aware autoscaling as in CarbonScaler, transparent live migration with CRIU, and a reinforcement-learning scheduler trained in the simulator are documented for subsequent work."));
children.push(pageBreak());

// ---------------------------------------------------------------- 8 conclusion (p14)
children.push(heading("Conclusion"));
children.push(body("The Carbon-Aware Autonomous Workload Orchestrator reframes carbon-aware scheduling around a quantity that prior systems left implicit: the carbon cost of moving a workload. By profiling migration on a real container platform, fitting a cost model and applying the Carbon Payback Period inside a Kubernetes controller, the project moves workloads only when the move pays back, while temporal shifting, latency constraints and a MILP reference keep the decisions complete and explainable. The result is a reproducible testbed and evaluation suite on which the final measurements will be reported."));
children.push(pageBreak());

// ---------------------------------------------------------------- 9 references (p15)
children.push(heading("References"));
children.push(sub("1. Data Sources"));
for (const t of ["National Grid ESO. Carbon Intensity API. Available online: https://carbonintensity.org.uk/",
  "ENTSO-E Transparency Platform. Available online: https://transparency.entsoe.eu/",
  "U.S. Energy Information Administration. Open Data API. Available online: https://www.eia.gov/opendata/",
  "Electricity Maps. Carbon Intensity API. Available online: https://www.electricitymaps.com/"]) children.push(bullet(null, t));
children.push(sub("2. Foundational Papers"));
for (const t of ["Radovanović, A. et al. (2022). Carbon-Aware Computing for Datacenters. IEEE Transactions on Power Systems.",
  "Wiesner, P. et al. (2021). Let's Wait Awhile: How Temporal Workload Shifting Can Reduce Carbon Emissions in the Cloud. Middleware.",
  "Hanafy, W. et al. (2024). CarbonScaler: Leveraging Cloud Workload Elasticity for Optimizing Carbon-Efficiency. SIGMETRICS.",
  "Souza, A. et al. (2023). CASPER: Carbon-Aware Scheduling and Provisioning for Distributed Web Services. IGSC.",
  "Souza, A. et al. (2023). Ecovisor: A Virtual Energy System for Carbon-Efficient Applications. ASPLOS.",
  "Lechowicz, A. et al. (2024). CarbonClipper: Optimal Algorithms for Carbon-Aware Spatiotemporal Workload Management.",
  "Clark, C. et al. (2005). Live Migration of Virtual Machines. NSDI."]) children.push(bullet(null, t));
children.push(sub("3. Software and Libraries"));
for (const t of ["Kubernetes and k3d — https://k3d.io/", "PuLP and CBC Solver — https://coin-or.github.io/pulp/", "scikit-learn — https://scikit-learn.org/"]) children.push(bullet(null, t));

const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: BODY } } } },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "●", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540, hanging: 300 } }, run: { font: FONT } } }] }] },
  sections: [{
    properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 20 })] })] }) },
    children,
  }],
});
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log(`wrote ${OUT} (${buf.length} bytes)`); });
