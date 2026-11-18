# Carbon-Aware Autonomous Workload Orchestrator

Research prototype (reduced scope). One question:

> **When does migrating a workload to a cleaner grid pay back the carbon cost of the migration itself?**

Everything in this repo exists to answer that with *measured* numbers on a real Kubernetes
testbed, then to evaluate a scheduler that only moves a workload when the answer is "yes".

New here? Read the [PRD](docs/00-prd.md) (problem, goals, scope, requirements, milestones, team),
then follow **For teammates** below.

```
            ENTSO-E / EIA / UK ESO / Electricity Maps
                          │  hourly gCO2e/kWh per region
                          ▼
                 ┌──────────────────┐
                 │ Carbon forecaster│  persistence / seasonal / gradient boosting (24 h)
                 └────────┬─────────┘
                          ▼
┌──────────────┐  ┌──────────────────────────────────────┐  ┌──────────────────────┐
│ k3d cluster  │  │ DECISION ENGINE                      │  │ Migration cost model │
│ node→region  │◄─┤  SLA filter → payback test → WAIT →  │◄─┤ E(S) = a·S + b       │
│ india sweden │  │  MILP (PuLP/CBC)                     │  │ measured by profiler │
│ france us uk │  │  → MOVE / WAIT / HOLD / REFUSE       │  │ + network kWh/GB     │
└──────┬───────┘  └──────────────────────────────────────┘  └──────────────────────┘
       │ checkpoint on SIGTERM → shared /checkpoints → restore on target node
       ▼
   telemetry (sqlite) → experiments/ → dashboard
```

## Actions

| action | meaning |
| --- | --- |
| `MOVE`   | migrate now; carbon saved over remaining runtime > migration carbon (payback met) |
| `WAIT`   | do not run this slot; a cleaner window exists before the deadline (temporal shift) |
| `HOLD`   | keep placement; no greener SLA-feasible region exists |
| `REFUSE` | a greener region exists **but** migration carbon ≥ carbon saved (payback not met) |

`REFUSE` vs `HOLD` is the whole research story: baseline "greenest region" never refuses.

## Live demo: real grid data, real decisions, hosted dashboard

`cao live tick` is the whole journey in one command, and a GitHub Action runs it every hour:

1. **Collect** live carbon intensity for six locations: North West England, London, South Wales
   (National Grid ESO), Denmark West (Energinet), France (RTE), India North (Electricity Maps, needs a key).
2. **Forecast** the next 24 h per grid with a model trained here: regularised boosted trees on
   day-ahead weather forecasts (Open-Meteo) plus history, blended with naive forecasts per horizon.
   Retrained every run, scored daily on unseen days. Details and study: [docs/07-forecaster.md](docs/07-forecaster.md).
   Each forecast carries an **uncertainty band** from two quantile models, recalibrated on every run from
   the last week of forecasts that have come true. Every forecast is logged and scored when its hour arrives.
   An **anomaly detector** on that log flags hours where a grid landed far outside what the model expected.
   Details: [docs/08-uncertainty-and-anomalies.md](docs/08-uncertainty-and-anomalies.md).
3. **Schedule** a rolling set of simulated jobs with the real engine: MOVE / WAIT / HOLD / REFUSE.
4. **Score** five policies on the same jobs: ours, ours with the 24 h MILP plan, ours fed a naive
   forecast (the gap to "ours" is the model's contribution), always-greenest, carbon-unaware.
5. **Publish** `site/data/live.json` plus the dashboard in `web/` (grid cards, forecast with its
   "why", model card with generalisation check and drivers, job placement, decision feed, scoreboard,
   payback calculator, what-is-real list).

Grid data, forecasts and decisions are real. The jobs are simulated and the migration cost constants
are placeholders until the profiler runs on the testbed; the dashboard says so in its Method section.

**Run it on any machine (macOS, Linux, Windows)**

```bash
cao live tick          # first run of a day ~4-5 min (90 days of history, model training + scoring); later runs ~25 s
cao live serve         # then open http://localhost:8080
```

On Windows use the same two commands in PowerShell after the *For teammates* setup. Work on any
machine, `git push`; on the other machine `git pull`. The hosted dashboard updates itself from `main`.

**Host it for free on GitHub Pages**

1. Repo -> Settings -> General -> Change visibility -> Public (free Pages needs a public repo; GitHub Pro allows private).
2. `git push`. The *Live dashboard* workflow runs and creates the `gh-pages` branch (Actions tab shows it).
3. Repo -> Settings -> Pages -> Source: *Deploy from a branch* -> `gh-pages` / `(root)` -> Save.
4. Open https://uday2k5.github.io/Carbon-aware-orchestrator/ . It refreshes up to three times an hour (GitHub may delay
   scheduled runs by a few minutes). Actions tab -> *Live dashboard* -> *Run workflow* forces a run.

**Switch India on**

Create a free key at https://www.electricitymaps.com/ (zone `IN-NO`), then:

- hosted: Repo -> Settings -> Secrets and variables -> Actions -> New repository secret, name `ELECTRICITY_MAPS_TOKEN`.
- local: put `ELECTRICITY_MAPS_TOKEN=...` in a `.env` file in the repo root (git-ignored).

India appears on the next run and starts collecting; its forecast switches on after ten days of history.

Settings live in `config/live.yaml` (locations, latency table, services, job arrival rate).

## For teammates: clone, run, test (≈10 minutes)

Needs only Git and Python 3.10–3.14 (3.14 is what the repo was built with). No Docker, no
Kubernetes, no API keys for this part. Ask Uday to add your GitHub username as a collaborator
first (repo is private).

**macOS / Linux / WSL2**

```bash
git clone https://github.com/Uday2k5/Carbon-aware-orchestrator.git
cd Carbon-aware-orchestrator
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,viz]"
pytest
python experiments/exp01_payback_boundary.py
python experiments/exp05_replay.py
open results/replay.html            # Linux: xdg-open results/replay.html
```

**Windows 11 (PowerShell)**

```powershell
git clone https://github.com/Uday2k5/Carbon-aware-orchestrator.git
cd Carbon-aware-orchestrator
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,viz]"
pytest
python experiments\exp01_payback_boundary.py
python experiments\exp05_replay.py
start results\replay.html
```

If PowerShell refuses to activate (`running scripts is disabled`), run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use cmd.exe with `.venv\Scripts\activate.bat`.

**What "it works" looks like**

| step | expected |
| --- | --- |
| `pip install -e ".[dev,viz]"` | ends with `Successfully installed ... carbon-aware-orchestrator-0.1.0` |
| `pytest` | `51 passed` in roughly a minute (CBC solver runs inside the tests) |
| `python experiments/exp01_payback_boundary.py` | `Job A ... -> MOVE`, `Job B ... -> REFUSE`, a payback table, a `M`/`R` grid, first line says `cost model: placeholder` |
| `python experiments/exp05_replay.py` | a 7-row policy table, then `replay json -> ... replay html -> ... replay gif -> ...` (≈1 min) |
| `results/replay.html` in a browser | header `hour 0 / 71`, five coloured region columns, dots; press ▶ play and dots move (checklist in *Try it in 3 minutes*) |
| `cao payback --state-gb 60 --power-kw 0.2 --ci-src 650 --ci-dst 50 --remaining-h 0.5` | `decision : REFUSE` |

**Common problems**

| symptom | fix |
| --- | --- |
| `cao: command not found` / `'cao' is not recognized` | venv not activated. Activate it, or run `python -m cao.cli ...` |
| pip tries to compile numpy/pandas for ages or fails | Python version without wheels. Install 3.12 or 3.13 from python.org (tick *Add to PATH*), delete `.venv`, redo |
| `ModuleNotFoundError: matplotlib` | `pip install -e ".[viz]"` |
| `pulp` says the CBC solver was not found | `pip install --force-reinstall pulp` (PuLP bundles CBC for Windows, macOS, Linux x86-64). On ARM Linux: `sudo apt install coinor-cbc` |
| `ssl` / certificate errors on macOS python.org build | run `/Applications/Python 3.x/Install Certificates.command` |
| tests slow (> 3 min) | normal on a busy laptop; run `pytest -q tests/test_payback.py` to check quickly |
| replay page blank | open it via a server instead: `python -m http.server 8765 --directory results` → http://localhost:8765/replay.html |
| no internet | everything above still works (synthetic data, fonts fall back) |

**How to contribute**

1. `git checkout -b feature/<short-name>` from an up-to-date `main`.
2. Put code in the module you own (see *Team split*); tests in `tests/`; notebooks in `notebooks/`.
3. `pytest` must be green; `ruff check cao tests` clean.
4. Push the branch, open a PR into `main`, one teammate reviews.
5. Never commit `data/processed/*`, `results/*`, `.env`, or any key file (all git-ignored, but check `git status` before `git add -A`).

Real-data work (member 2) and the cluster (member 1) start in [docs/04-day1-install.md](docs/04-day1-install.md).

## Quickstart (any OS, no cluster, no API keys)

```bash
python3 -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                                                    # ~40 tests, <1 min (includes CBC solves)

cao payback --state-gb 0.2 --power-kw 0.2 --ci-src 650 --ci-dst 50 --remaining-h 2    # Job A -> MOVE
cao payback --state-gb 60  --power-kw 0.2 --ci-src 650 --ci-dst 50 --remaining-h 0.5  # Job B -> REFUSE
cao boundary --power-kw 0.2 --ci-src 650 --ci-dst 50                                  # payback vs state size

cao profile --smoke                        # real local checkpoint/transfer/restore measurements
cao fit results/migration_profile_smoke.csv --out config/migration_model.json   # a, b per phase

python experiments/exp01_payback_boundary.py       # THE experiment (MOVE/REFUSE grid)
python experiments/exp02_policy_comparison.py      # 6 baselines vs proposed vs oracle (MILP: minutes)
python experiments/exp03_forecast_sensitivity.py   # regret vs forecast error
python experiments/exp04_network_energy_sensitivity.py
python experiments/exp05_replay.py                 # visual replay: results/replay.html + replay.gif
python experiments/exp06_forecaster_study.py       # forecaster vs naive, over/under-fit check (after `cao live tick`)
python experiments/exp07_forecast_value.py         # what the forecast is worth to greedy vs MILP (about 30 min)
```

## Visual replay (for demos / viva)

```bash
cao simulate --hours 72 --jobs 16 --export results/replay.json
cao replay results/replay.json --html results/replay.html --gif results/replay.gif [--mp4 results/replay.mp4] [--policy greenest-region]
```

- `replay.html` is self-contained (data embedded, no server, no install): open it in any browser.
  Hour slider / play, policy switch, region columns coloured by live CI, jobs as dots that jump on
  MOVE (arrow), hollow while WAITing, red ring on REFUSE, progress ring, cumulative-carbon race of
  every policy, decision log, payback-boundary heatmap. Space / ← / → keys work. "load JSON" opens
  any other export.
- `replay.gif` (Pillow) / `replay.mp4` (needs ffmpeg) is the same scene rendered with matplotlib
  for slides. `--hours 72 --fps 4` gives an 18 s clip; `--policy` picks which policy to animate.

### Try it in 3 minutes

```bash
source .venv/bin/activate                      # Windows: .venv\Scripts\activate
pip install -e ".[dev,viz]"                    # matplotlib + pillow for the GIF
python experiments/exp05_replay.py             # ~1 min: simulates 72 h x 16 jobs, all policies, writes results/replay.*
open results/replay.html                       # macOS;  Windows: start results\replay.html;  Linux: xdg-open results/replay.html
```

What you should see in the browser (no server, works offline, fonts fall back to system if no internet):

1. Header shows `hour 0 / 71 · 2026-01-01 00:00 UTC`, policy dropdown preselects `migration-aware-milp`.
2. Five region columns (india, sweden, france, us-east, uk) tinted green→red by their current CI, value printed under each name.
3. Coloured dots = jobs (orange ML, violet batch, green web). Dot size grows with state GB; white ring fills as the job progresses; dashed hollow dots are waiting.
4. Press **▶ play** (or space): dots jump between columns on **MOVE** with a cyan arrow, get a yellow ring on **WAIT**, a red ring on **REFUSE**. `←`/`→` step one hour, the slider scrubs.
5. Right rail: KPI tiles (total / execution / migration g, migrations, refused moves, wait slots, jobs done) and the cumulative-carbon race of every policy; the selected policy is the thick line.
6. Bottom left: decision log (newest first) with saved g, migration g and payback hours per event. Bottom right: payback-boundary table, MOVE cells green, REFUSE cells red.
7. Switch the dropdown to `greenest-region`: many more arrows, no REFUSE, higher migration g. Switch to `carbon-unaware`: nothing ever moves.
8. Hover any dot for its job card and last decision reason. `load JSON` opens any other `cao simulate --export` file.

Open `results/replay.gif` in any image viewer / drop it into PowerPoint; it is the same scene for one policy.

Regenerate for other settings:

```bash
cao simulate --hours 168 --jobs 20 --seed 3 --export results/replay.json           # or --data data/processed/ci_all.csv
cao replay results/replay.json --html results/replay.html                           # page only
cao replay results/replay.json --gif results/replay.gif --policy greenest-region --fps 6 --hours 48
cao replay results/replay.json --mp4 results/replay.mp4                             # needs ffmpeg on PATH
pytest tests/test_replay.py                                                         # export / html / gif smoke tests
```

Troubleshooting: blank page → the browser blocked the inline script from `file://`? It should not, but
serving the folder works too: `python -m http.server 8765 --directory results` then
http://localhost:8765/replay.html. Dots overlap → fewer jobs (`--jobs 10`). GIF too big for slides →
`--hours 48 --fps 3 --dpi 80`.

Until `cao profile` + `cao fit` have run, the cost model uses the **placeholder** constants in
`config/regions.yaml` (labelled `source: placeholder` in every output). Never report those.

## Real data

```bash
cao carbon fetch --source uk --region uk --grid GB --start 2026-01-01 --end 2026-03-01 --out data/processed/ci_uk.csv --store
ENTSOE_TOKEN=... cao carbon fetch --source entsoe --region sweden --grid SE_3 --start ... --end ... --out data/processed/ci_se.csv --store
ENTSOE_TOKEN=... cao carbon fetch --source entsoe --region france --grid FR ...
EIA_API_KEY=...  cao carbon fetch --source eia --region us-east --grid PJM ...
ELECTRICITY_MAPS_TOKEN=... cao carbon fetch --source electricity-maps --region india --grid IN-WE ...   # 24 h/call; schedule it
cao simulate --data data/processed/ci_all.csv --jobs 20 --seed 1
```

`cao carbon synth` produces labelled synthetic traces so everything runs offline.

MILP runtime: PuLP builds the model in Python and CBC solves it; a dense tick (20 concurrent
jobs, 5 regions, 24 h) takes a few seconds. `MilpPolicy(replan_every=3)` reuses the plan for
intermediate slots; `--no-milp` skips it. The greedy `migration-aware` policy is instant.

## Kubernetes testbed (main developer, WSL2/Linux)

```bash
bash deploy/k3d/create-cluster.sh carbon      # 5 agents labelled topology.carbon-aware.io/region=<r>
bash deploy/workloads/build.sh carbon         # ml-training / batch / web-service images
kubectl apply -f deploy/k8s/workloads/
cao carbon synth --store                      # or real data
cao controller --dry-run --interval 60        # decisions only
cao controller --interval 300 --checkpoints-dir ~/cao-checkpoints   # applies MOVE
```

Migration mechanism (cooperative, application-level): the controller patches the Deployment's
`nodeSelector`; kubelet SIGTERMs the old pod, which writes a final checkpoint to the shared
`/checkpoints` volume; the new pod on the target "region" restores it. Downtime and checkpoint
time are recorded to sqlite (`migrations` table). CRIU / kubelet checkpoint API is a
documented alternative, not in scope.

## Repo layout

```
cao/
  core/        Job, Decision, units, config
  carbon/      sources (uk, entsoe, eia, electricity-maps, synthetic), schema, emission factors
  energy/      power model, RAPL, EnergyMeter (psutil), Kepler query
  migration/   cost model (a·S+b, network kWh/GB, fit), profiler, transports
  forecast/    features, persistence / seasonal / gradient-boosting (+xgboost), backtest
  decision/    payback, simple MOVE/REFUSE, temporal WAIT, SLA, MILP, engine
  simulator/   traces + jobs + 6 policies + oracle, accounting, metrics
  k8s/         client (real + fake), controller, cooperative migrate
  dashboard/   FastAPI api, Streamlit app
  replay/      simulation replay: JSON export, self-contained HTML page, matplotlib GIF/MP4
  live/        live pipeline: grid feeds, hourly store, forecasting, scheduling twin, dashboard JSON
  db/          sqlite store
  cli.py       `cao ...`
config/        regions.yaml (regions, latency, power model, placeholders), migration_model.json (fitted)
web/           live dashboard (static: index.html, styles.css, app.js)
deploy/        k3d script, workload containers, k8s manifests, controller RBAC
experiments/   exp01..exp05 (exp05 = visual replay)
tests/         pytest
docs/          research framing, architecture, math, install, week plan, schema
```

## Team split

| who | owns | environment |
| --- | --- | --- |
| Member 1 (main) | `k8s/`, `migration/profiler`, `energy/`, cluster, controller | WSL2 + Ubuntu, Docker, k3d, kubectl |
| Member 2 | `carbon/`, `forecast/`, notebooks, EXP-03 | Windows + Python |
| Member 3 | `simulator/`, `decision/milp`, `dashboard/`, EXP-02/04, paper figures | Windows + Python |

Shared contract: `cao.core.models.Job` / `Decision`, `MigrationCostModel`, the CI csv schema.

## Docs

- [docs/00-prd.md](docs/00-prd.md) — product requirements: problem, goals, scope, functional requirements with status, metrics, milestones, risks
- [docs/01-research-framing.md](docs/01-research-framing.md) — gap, hypotheses, novelty table, baselines, mandatory papers
- [docs/02-architecture.md](docs/02-architecture.md) — components, data flow, migration sequence
- [docs/03-math-model.md](docs/03-math-model.md) — payback period, cost model, MILP
- [docs/04-day1-install.md](docs/04-day1-install.md) — per-member install lists (Windows 11)
- [docs/05-week-plan.md](docs/05-week-plan.md) — 12-week plan for 3 students
- [docs/06-database-schema.md](docs/06-database-schema.md) — sqlite tables
- [docs/07-forecaster.md](docs/07-forecaster.md) — the trained carbon forecaster: design, study, over/under-fit check, limits
- [docs/08-uncertainty-and-anomalies.md](docs/08-uncertainty-and-anomalies.md) — uncertainty band, live track record, anomaly detector

## Scope (deliberately reduced)

In: spatial migration, temporal shifting, SLA constraint, measured migration cost, MILP,
payback boundary, Kubernetes demo, baselines + oracle, forecast sensitivity.
Out: carbon-aware autoscaling (CarbonScaler `SCALE` action), CRIU live migration, multi-cluster
federation, cost (money) optimisation. Discuss in related/future work only.
