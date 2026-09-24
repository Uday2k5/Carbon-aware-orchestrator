# Carbon-Aware Autonomous Workload Orchestrator

Research prototype (reduced scope). One question:

> **When does migrating a workload to a cleaner grid pay back the carbon cost of the migration itself?**

Everything in this repo exists to answer that with *measured* numbers on a real Kubernetes
testbed, then to evaluate a scheduler that only moves a workload when the answer is "yes".

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
```

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
  db/          sqlite store
  cli.py       `cao ...`
config/        regions.yaml (regions, latency, power model, placeholders), migration_model.json (fitted)
deploy/        k3d script, workload containers, k8s manifests, controller RBAC
experiments/   exp01..exp04
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

- [docs/01-research-framing.md](docs/01-research-framing.md) — gap, hypotheses, novelty table, baselines, mandatory papers
- [docs/02-architecture.md](docs/02-architecture.md) — components, data flow, migration sequence
- [docs/03-math-model.md](docs/03-math-model.md) — payback period, cost model, MILP
- [docs/04-day1-install.md](docs/04-day1-install.md) — per-member install lists (Windows 11)
- [docs/05-week-plan.md](docs/05-week-plan.md) — 12-week plan for 3 students
- [docs/06-database-schema.md](docs/06-database-schema.md) — sqlite tables

## Scope (deliberately reduced)

In: spatial migration, temporal shifting, SLA constraint, measured migration cost, MILP,
payback boundary, Kubernetes demo, baselines + oracle, forecast sensitivity.
Out: carbon-aware autoscaling (CarbonScaler `SCALE` action), CRIU live migration, multi-cluster
federation, cost (money) optimisation. Discuss in related/future work only.
