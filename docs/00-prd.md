# PRD — Carbon-Aware Autonomous Workload Orchestrator (reduced scope)

| | |
| --- | --- |
| Version | 1.0 — 2026-09-24 |
| Status | Scope approved, implementation v0.1 in repo |
| Owner | Uday Kumar (main developer) |
| Team | 3 students (see §14) |
| Repo | https://github.com/Uday2k5/Carbon-aware-orchestrator |

## 1. Summary

A research prototype that decides **when moving a running workload to a cleaner electricity grid is
actually worth it once the carbon cost of the move itself is counted**. It measures migration cost
(checkpoint, transfer, restore) on a real Kubernetes testbed, folds those measurements and the
network transfer energy into a scheduler, and evaluates that scheduler against the standard
carbon-aware baselines on real grid carbon-intensity data. The deliverables are a working system,
reproducible experiments, a visual replay for presentations, and a defensible research story built
around one metric: the **Carbon Payback Period**.

## 2. Problem

Carbon-aware scheduling (Google CICS, Let's Wait Awhile, CarbonScaler, CASPER, CarbonClipper) shifts
work in time and space towards cleaner electricity. Spatial shifting means *migrating* state across
regions, and migration is not free: checkpointing, transferring gigabytes over a network and
restoring all consume energy, and the workload is down meanwhile. A scheduler that ignores this
("always run in the greenest region") can emit more carbon than doing nothing, especially for
large-state, short-remaining jobs. Prior work models movement cost theoretically (CarbonClipper) or
leaves it out; almost none *measures* it on a real container platform and studies the resulting
break-even behaviour.

## 3. Goals and non-goals

**Goals**

| id | goal | measurable outcome |
| --- | --- | --- |
| G1 | Measure migration cost as a function of state size on Kubernetes | fitted `E_phase(S) = a·S + b` per phase with R² ≥ 0.9, from ≥ 6 sizes × 3 repeats |
| G2 | Ship a scheduler whose migrations always pay back | `REFUSE` issued whenever saved carbon < migration carbon; 0 SLA violations |
| G3 | Quantify the benefit vs. cost-blind policies | total gCO₂e of proposed policy < greenest-region on real traces, deadlines respected |
| G4 | Quantify the value of forecasts | regret vs. oracle as a function of forecast error (EXP-03) |
| G5 | Demonstrate on a live cluster | ≥ 10 real controller-driven migrations on k3d with measured downtime |
| G6 | Present it | self-contained replay page + GIF, paper-ready figures, viva-ready explanation of payback |

**Non-goals (explicitly out of scope, listed in related/future work only)**

- Carbon-aware autoscaling / elasticity (CarbonScaler `SCALE` action)
- CRIU / kubelet checkpoint-API live migration; multi-cluster federation; service meshes
- Monetary cost optimisation, spot pricing
- Production hardening (HA controller, auth, multi-tenant)
- Forecasting research beyond a solid gradient-boosting baseline

## 4. Users and stakeholders

| who | needs |
| --- | --- |
| Team member 1 (infra) | reproducible cluster, profiler, controller; clear measurement protocol |
| Team member 2 (forecasting) | clean hourly CI dataset, feature/model code, evaluation harness |
| Team member 3 (evaluation) | simulator with true-cost accounting, baselines, figures, replay |
| Supervisor / examiners | honest research gap, testable hypotheses, measured (not invented) constants, clear demo |
| Later readers | one command to reproduce every figure; labelled placeholders vs measurements |

## 5. Research questions and hypotheses

**RQ.** What happens when the carbon cost of migration is explicitly *measured* and incorporated into
carbon-aware workload scheduling?

- **H1.** Incorporating empirically measured migration costs reduces total lifecycle carbon compared
  with migration policies that treat movement as cost-free, while maintaining deadlines and latency
  constraints. → EXP-02.
- **H2.** The benefit of geographical migration depends strongly on state size and remaining
  execution time, producing a measurable Carbon Payback Period beyond which migration becomes
  beneficial. → EXP-01 with the fitted cost model.

Key formula: `CPP = MigrationCarbon / (P·CI_src − P·CI_dst)`; `MOVE ⇔ remaining_h > CPP`.

## 6. Scope

| in scope | out of scope |
| --- | --- |
| Spatial migration (MOVE) with measured cost | Autoscaling (SCALE) |
| Temporal shifting (WAIT) with 24 h forecast | Forecast horizons > 24 h |
| Hard latency SLA for web services | Soft/probabilistic SLOs |
| Greedy engine + MILP (PuLP/CBC) | Custom online algorithms with competitive proofs |
| 5 logical regions on one k3d cluster, real CI traces replayed | Real multi-region deployment |
| Cooperative app-level checkpoint on SIGTERM | CRIU / transparent live migration |
| Synthetic + real CI data (UK ESO, ENTSO-E, EIA, Electricity Maps) | Buying historical India data |
| Simulator, 6 policies + oracle, regret | Game-theoretic / multi-tenant fairness |
| Replay HTML + GIF, Streamlit/FastAPI dashboard | Public web hosting |

## 7. System overview

```
carbon sources → hourly CI dataset → forecaster (24 h)
                                          ↓
  k3d cluster (pods + node region labels) → controller → DecisionEngine → MOVE / WAIT / HOLD / REFUSE
                                          ↑                    ↑
                     energy meter / profiler → MigrationCostModel (a·S+b, kWh/GB)
                                          ↓
                          sqlite telemetry → experiments → figures / replay
```

Details: [02-architecture.md](02-architecture.md). Maths: [03-math-model.md](03-math-model.md).

## 8. Functional requirements

Status as of v0.1: ✅ done · 🟡 partial · ⬜ todo (team work).

**Carbon data (FR-CD)**

| id | requirement | acceptance | status |
| --- | --- | --- | --- |
| CD-1 | Fetch hourly CI for GB from UK ESO without a key | `cao carbon fetch --source uk` writes normalized csv | ✅ |
| CD-2 | Fetch ENTSO-E generation mix (SE_3, FR) and convert to CI with IPCC factors | csv with `source=entsoe` | ✅ code, ⬜ token + run |
| CD-3 | Fetch EIA hourly fuel mix (PJM) and convert to CI | csv with `source=eia` | ✅ code, ⬜ key + run |
| CD-4 | India CI via Electricity Maps (IN-WE), scheduled collection | ≥ 30 days collected | ✅ code, ⬜ collection |
| CD-5 | One schema: `timestamp (UTC hourly), region, ci_g_per_kwh, source`; gaps ≤ 3 h interpolated | `normalize()` tests | ✅ |
| CD-6 | Deterministic synthetic traces for offline dev, always labelled `synthetic` | same output across processes | ✅ |
| CD-7 | Store in sqlite + csv | `carbon_intensity` table | ✅ |

**Energy measurement (FR-EN)**

| id | requirement | acceptance | status |
| --- | --- | --- | --- |
| EN-1 | Joules for a code block via RAPL when available, else utilisation power model | `EnergyMeter` context manager, method reported | ✅ |
| EN-2 | Power model calibrated with a wall-plug meter; constants in config with provenance | idle/max watts documented | ⬜ |
| EN-3 | Per-pod energy from Kepler/Prometheus when the cluster has it | `query_container_joules()` | ✅ code, ⬜ deployed |

**Migration profiler and cost model (FR-MP / FR-CM)**

| id | requirement | acceptance | status |
| --- | --- | --- | --- |
| MP-1 | Measure checkpoint, transfer, restore time and energy for S ∈ {0.1, 0.5, 1, 5, 10, 20} GB, ≥ 3 repeats | `results/migration_profile.csv` | ✅ tool, ⬜ testbed run |
| MP-2 | Transfer over loopback TCP, optionally shaped with `tc netem` (delay, bandwidth) | `--transport loopback / netem` | ✅ |
| CM-1 | Fit `E = a·S + b` per phase, report R², clamp to physical (a ≥ 0) | `cao fit` → `migration_model.json` | ✅ |
| CM-2 | Network energy `S × kWh/GB` with CI attribution mode (src / dst / mean) | parameter + EXP-04 | ✅ |
| CM-3 | Downtime model `d(S)` from measured phase times | in fitted json | ✅ |
| CM-4 | Every output states whether constants are `placeholder` or `measured` | label in CLI, replay, experiments | ✅ |

**Decision engine (FR-DE)**

| id | requirement | acceptance | status |
| --- | --- | --- | --- |
| DE-1 | Payback test: MOVE iff saved > migration carbon, else REFUSE; HOLD if no greener region | unit tests on plan's Job A / Job B | ✅ |
| DE-2 | Temporal WAIT: choose cheapest start window within deadline | tests | ✅ |
| DE-3 | Hard SLA filter by RTT matrix; immovable jobs | tests | ✅ |
| DE-4 | Joint MILP over 24 h: residence + execution + state movement + pause cost + capacity + contiguity | optimal on small instances, tests | ✅ |
| DE-5 | Decode MILP into MOVE / WAIT / HOLD / REFUSE with payback numbers in the reason | tests | ✅ |
| DE-6 | Hysteresis margin, evaluation horizon for always-on services | config | ✅ |
| DE-7 | Dense tick (20 jobs, 5 regions, 24 slots) solves in < 2 s on a laptop | benchmark 0.4 s | ✅ |

**Forecasting (FR-FC)**

| id | requirement | acceptance | status |
| --- | --- | --- | --- |
| FC-1 | Persistence and seasonal-naive baselines | `compare_models` | ✅ |
| FC-2 | Direct multi-horizon gradient boosting (sklearn; XGBoost optional) | beats persistence MAE on synthetic | ✅ |
| FC-3 | Prediction intervals from residual spread per horizon | `predict_interval` | ✅ |
| FC-4 | Rolling-origin backtest MAE/MAPE per horizon | `backtest()` | ✅ |
| FC-5 | Trained model on ≥ 60 days of real data per region, report table | notebooks / EXP-03 | ⬜ |

**Simulator and evaluation (FR-SIM)**

| id | requirement | acceptance | status |
| --- | --- | --- | --- |
| SIM-1 | Hourly discrete-time simulation charging *true* execution, migration and resume carbon to every policy | tests | ✅ |
| SIM-2 | Policies: carbon-unaware, greenest-region, wait-only, move-only, migration-aware, migration-aware-milp, oracle | `default_policies()` | ✅ |
| SIM-3 | Forecast providers: oracle, noisy(σ), persistence, seasonal-naive, trained model | tests | ✅ |
| SIM-4 | Workload generator for ML training / batch / web service with deadlines and SLAs, seeded | tests | ✅ |
| SIM-5 | Metrics: total g, exec g, migration g, migrations, deadline violations, SLA-violation slots, regret | `compare_policies()` | ✅ |
| SIM-6 | Multi-seed runs with mean ± std | `metrics.summarize` | ✅ |

**Kubernetes (FR-K8S)**

| id | requirement | acceptance | status |
| --- | --- | --- | --- |
| K8-1 | k3d cluster with 5 agents labelled `topology.carbon-aware.io/region` and a shared `/checkpoints` volume | script | ✅ script, ⬜ run |
| K8-2 | Three workload images that checkpoint on SIGTERM / SIGUSR1 and restore on start, writing metrics.json | Dockerfiles + code | ✅ code, ⬜ built |
| K8-3 | Controller: pods + annotations → Jobs → engine → patch Deployment nodeSelector; dry-run mode | fake-client tests | ✅ |
| K8-4 | Record each migration's downtime and checkpoint time to sqlite | `migrations` table | ✅ code, ⬜ real data |
| K8-5 | ≥ 10 real migrations compared to the cost model's predictions | report table | ⬜ |

**Visualisation (FR-VIS)**

| id | requirement | acceptance | status |
| --- | --- | --- | --- |
| VIS-1 | Self-contained HTML replay: hour scrubber, policy switch, region CI colouring, MOVE/WAIT/REFUSE glyphs, carbon race, decision log, payback table | `results/replay.html` opens offline | ✅ |
| VIS-2 | GIF/MP4 of the same scene for slides | `cao replay --gif` | ✅ |
| VIS-3 | Streamlit dashboard and FastAPI endpoints over sqlite | run instructions | ✅ code, ⬜ exercised |

**CLI / packaging (FR-CLI)**

`cao carbon synth|fetch`, `cao profile`, `cao fit`, `cao payback`, `cao boundary`, `cao forecast`,
`cao simulate [--export]`, `cao replay`, `cao controller` — all ✅, documented in README.

## 9. Non-functional requirements

| id | requirement |
| --- | --- |
| NF-1 | Reproducibility: every experiment seeded; synthetic traces identical across processes; results csv carry parameters |
| NF-2 | Runtime: `pytest` < 1 min; EXP-01/03/04 < 5 s; EXP-02 (7 days, MILP) < 2 min; EXP-05 < 1 min |
| NF-3 | Portability: Python ≥ 3.9 on Windows, macOS, Linux; cluster parts Linux/WSL2 only |
| NF-4 | No paid service required to run anything: synthetic data path always works and is labelled |
| NF-5 | Honesty labels: `placeholder` vs `measured` on every number that could be reported |
| NF-6 | Quality: pytest suite green on `main`, ruff clean, PRs reviewed by one teammate |
| NF-7 | Secrets: API keys only via `.env` (git-ignored); key files ignored by pattern |

## 10. Data

- Schema: `timestamp, region, ci_g_per_kwh, source` (UTC, hourly).
- Sources: UK ESO (free), ENTSO-E (free token), EIA (free key), Electricity Maps (free tier, 24 h/call — collect daily), synthetic (labelled).
- Storage: `data/processed/*.csv` (git-ignored, share via drive), `results/cao.sqlite`; `data/sample/ci_synthetic_7d.csv` committed for smoke runs.
- Emission factors: IPCC AR5 medians (`cao/carbon/emission_factors.py`).
- India: no official real-time API; Electricity Maps zone `IN-WE` or CEA monthly averages; document the choice.

## 11. Success metrics

| metric | target |
| --- | --- |
| Fit quality of migration model | R² ≥ 0.9 per phase, ≥ 18 measurements |
| Proposed vs greenest-region (real traces, ≥ 5 seeds) | lower total gCO₂e, 0 SLA-violation slots, deadline violations ≤ baseline |
| Proposed vs carbon-unaware | ≥ 20 % reduction on the studied traces (report actual) |
| Regret vs oracle at forecast MAPE of the trained model | reported curve, < 5 % of total for σ ≤ 0.1 |
| Live demo | ≥ 10 controller migrations, measured downtime within ±30 % of `d(S)` |
| Payback boundary | figure: state size × remaining hours → MOVE/REFUSE, from measured constants |

## 12. Experiments

| id | script | question | main figure |
| --- | --- | --- | --- |
| EXP-01 | `exp01_payback_boundary.py` | where is the MOVE/REFUSE boundary? | payback hours vs state size; MOVE/REFUSE grid |
| EXP-02 | `exp02_policy_comparison.py` | does measured cost help? (H1) | total carbon per policy, stacked exec/migration |
| EXP-03 | `exp03_forecast_sensitivity.py` | what does forecast error cost? | regret vs σ, vs persistence/seasonal |
| EXP-04 | `exp04_network_energy_sensitivity.py` | how much does kWh/GB matter? | payback hours and totals vs kWh/GB |
| EXP-05 | `exp05_replay.py` | show it | replay page + GIF |
| EXP-06 | *(todo, member 1)* live k3d migrations vs model | model validity | measured vs predicted downtime/energy |

## 13. Milestones

| M | when | done when |
| --- | --- | --- |
| M1 | week 1 | repo runs on all three machines, real UK + ENTSO-E data flowing |
| M2 | week 2 | **fitted `config/migration_model.json`** from the testbed, EXP-01 with measured constants |
| M3 | week 4 | EXP-02 on real traces, forecast baselines + GBR evaluated |
| M4 | week 6 | end-to-end demo: controller moves a pod, downtime recorded |
| M5 | week 9 | all figures multi-seed, dashboard, replay, draft paper |
| M6 | week 12 | submission + viva demo |

Detailed week plan: [05-week-plan.md](05-week-plan.md).

## 14. Team and ownership

| member | owns | environment |
| --- | --- | --- |
| 1 (Uday, main) | `k8s/`, `migration/profiler`, `energy/`, cluster, controller, EXP-06 | WSL2 + Ubuntu, Docker, k3d |
| 2 | `carbon/`, `forecast/`, notebooks, EXP-03, data collection | Windows + Python |
| 3 | `simulator/`, `decision/milp`, `replay/`, `dashboard/`, EXP-02/04/05, figures | Windows + Python |

Shared contracts: `Job` / `Decision` (`cao/core/models.py`), `MigrationCostModel`, the CI csv schema.
Branches `feature/<name>`, PR into `main`, `pytest` green, one review.

## 15. Risks and mitigations

| risk | impact | mitigation |
| --- | --- | --- |
| RAPL unavailable (macOS, most WSL2) | energy is model-based | calibrate power model with a wall meter; report method; RAPL/Kepler on a Linux box if available |
| India CI data hard to get | one region synthetic | Electricity Maps daily collection from week 1; fallback CEA averages, labelled |
| k3d shared volume makes transfer local | network cost not measured in-cluster | profile transfer separately over loopback/netem; model network as kWh/GB; state clearly |
| kWh/GB literature spans 10× | boundary shifts | EXP-04 sensitivity is a headline result, not a footnote |
| MILP too slow on dense instances | evaluation slow | departure/arrival formulation (done), 0.5 % gap, `replan_every`, greedy fallback |
| Forecast quality poor | WAIT decisions hurt | EXP-03 quantifies; engine works with persistence forecasts |
| Scope creep (autoscaling, CRIU) | nothing finished | non-goals list; discuss in future work only |
| Secrets in repo | leaked keys | `.env` only, key patterns ignored, review `git status` before `git add -A` |

## 16. Assumptions and limitations (state in the paper)

- A1 One laptop, one physical grid; regions emulated by replaying real CI traces.
- A2 Workload energy from a utilisation power model unless RAPL/Kepler available; calibration reported.
- A3 Pausing a preemptible job costs one checkpoint + restore; waiting itself is free.
- A4 Network transfer energy = bytes × kWh/GB; CI attributed to the mean of source and destination grids.
- A5 Migration downtime reduces useful execution in the slot where it occurs.
- L1 Oracle is the same receding-horizon policy with perfect forecasts, not a global optimum; regret can be slightly negative.
- L2 Synthetic traces are for pipeline validation only; no synthetic number is a finding.

## 17. Decisions log

| date | decision |
| --- | --- |
| 2026-09-24 | Scope reduced: no SCALE, no CRIU; build order profiler → payback → WAIT → SLA → MILP → sim → k8s |
| 2026-09-24 | Network energy default 0.06 kWh/GB (Aslan et al.), sensitivity mandatory |
| 2026-09-24 | Migration = cooperative checkpoint on SIGTERM + nodeSelector patch |
| 2026-09-24 | `config/migration_model.json` committed only when fitted on the Linux testbed |

## 18. Glossary

**CI** carbon intensity, gCO₂e/kWh · **CPP** carbon payback period, hours · **MOVE/WAIT/HOLD/REFUSE**
scheduler actions · **regret** extra carbon vs the oracle policy · **state** checkpointable data that
must travel with a job (GB) · **slot** one scheduling interval (1 h) · **k3d** k3s Kubernetes in Docker.

## 19. References

1. Lechowicz et al., *CarbonClipper*, 2024. 2. Wiesner et al., *Let's Wait Awhile*, Middleware 2021.
3. Hanafy et al., *CarbonScaler*, SIGMETRICS 2024. 4. Souza et al., *CASPER*, IGSC 2023.
5. Souza et al., *Ecovisor*, ASPLOS 2023. 6. Clark et al., *Live Migration of Virtual Machines*, NSDI 2005.
7. Radovanović et al., *Carbon-Aware Computing for Datacenters*, IEEE TPS 2022.
Supporting: Aslan et al. 2018 (kWh/GB); IPCC AR5 WG3 Annex III (emission factors); Fan et al. 2007 (linear power model).
