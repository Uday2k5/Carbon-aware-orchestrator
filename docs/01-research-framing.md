# Research framing

## Research question

*What happens when the carbon cost of migration is explicitly **measured** and incorporated into
carbon-aware workload scheduling?*

## Hypotheses

**H1.** Incorporating empirically measured migration costs into carbon-aware workload scheduling
reduces total lifecycle carbon emissions compared with migration policies that treat workload
movement as cost-free, while maintaining workload deadlines and latency constraints.

**H2.** The benefit of geographical workload migration depends strongly on workload state size and
remaining execution time, producing a measurable carbon payback period beyond which migration
becomes beneficial.

Tests: H1 → `experiments/exp02_policy_comparison.py` (greenest-region vs migration-aware, same
jobs/traces, true costs charged to both). H2 → `experiments/exp01_payback_boundary.py` with the
*fitted* `config/migration_model.json`.

## Research gap (safe wording)

Existing research has demonstrated temporal carbon shifting (Wiesner et al.), carbon-aware
geographical workload management (Radovanović et al.; Lechowicz et al.), carbon-aware
elasticity (Hanafy et al.) and SLO-aware carbon scheduling (Souza et al.). CarbonClipper
explicitly models movement costs in its theoretical formulation. **Therefore the gap is not
"previous work ignores migration cost".** Our contribution is the empirical measurement and
system-level integration of migration energy and transfer overhead into a Kubernetes
carbon-aware controller, and the evaluation of the resulting break-even (payback) behaviour
using measured migration characteristics.

## What is and is not novel

| existing work | idea we reuse |
| --- | --- |
| Google CICS (Radovanović et al. 2022) | shift work by grid carbon signal (industrial baseline) |
| Let's Wait Awhile (Wiesner et al. 2021) | temporal shifting, forecast-accuracy sensitivity → `WAIT` |
| CarbonScaler (Hanafy et al. 2023) | Kubernetes implementation, elasticity → related/future work only |
| CarbonClipper (Lechowicz et al. 2024) | online spatiotemporal optimisation with movement cost → MILP framing |
| CASPER (Souza et al. 2023) | carbon vs latency SLO as hard constraint → `sla.py` |
| Ecovisor (Souza et al. 2023) | expose energy/carbon telemetry to the application layer → energy meter |
| Clark et al. 2005 | live migration has measurable overhead (state, downtime) → profiler |

**Our combination:** carbon intensity + forecast + Kubernetes + *measured* migration energy +
network transfer cost + SLA constraint + MILP + Carbon Payback Period + real demo.

## Baselines (all charged the same true costs by the simulator)

1. `carbon-unaware` — fixed placement, run ASAP (plain Kubernetes).
2. `greenest-region` — always move to the min-CI feasible region; ignores migration cost.
3. `wait-only` — never migrates; temporal shifting only.
4. `move-only` — payback-aware migration, never delays.
5. `migration-aware` (proposed, greedy) / `migration-aware-milp` (proposed, joint).
6. `oracle-*` — proposed policy with perfect forecasts → regret = cost of forecast error.

## Metrics

total gCO2e (execution + migration + resume), migrations, deadline violations, SLA-violation
slots, mean completion time, regret vs oracle, and the **Carbon Payback Boundary**
(min remaining runtime for MOVE as a function of state size and CI gap).

Note on regret: `oracle-*` is the *same receding-horizon policy* with perfect forecasts, not a
global optimum. Because the MILP re-plans every slot over a 24 h window and is solved to a
0.5 % gap, a noisy-forecast run can occasionally beat it by a few grams (negative regret).
Report regret over several seeds (`--seeds 5`) and, for a tighter reference, set
`gap_rel=0` / a longer horizon in `solve_milp`.

## Assumptions to state in the report

- A1 Regions are emulated: one laptop, one physical grid; CI traces of other grids are replayed.
- A2 Workload energy = utilisation power model (or RAPL/Kepler where available), calibrated
  with a wall meter; report the calibration.
- A3 Pausing a preemptible job costs one checkpoint + restore (no network); waiting itself is free.
- A4 Network transfer energy = bytes × kWh/GB (parameter; sensitivity in EXP-04); CI attributed to
  the mean of source and destination grids.
- A5 Migration downtime reduces useful execution in the slot where it happens.

## Mandatory reading (7 papers)

1. Lechowicz, Christianson, Sun, Bashir, Hajiesmaili, Wierman, Shenoy. *CarbonClipper: Optimal Algorithms for Carbon-Aware Spatiotemporal Workload Management*. 2024.
2. Wiesner, Behnke, Scheinert, Gontarska, Thamsen. *Let's Wait Awhile: How Temporal Workload Shifting Can Reduce Carbon Emissions in the Cloud*. Middleware 2021.
3. Hanafy, Liang, Bashir, Irwin, Shenoy. *CarbonScaler: Leveraging Cloud Workload Elasticity for Optimizing Carbon-Efficiency*. SIGMETRICS 2024.
4. Souza, Jasoria, Chakrabarty, Bridgwater, Lundberg, Skogh, Ali-Eldin, Irwin, Shenoy. *CASPER: Carbon-Aware Scheduling and Provisioning for Distributed Web Services*. IGSC 2023.
5. Souza, Bashir, Murillo, Hanafy, Liang, Irwin, Shenoy. *Ecovisor: A Virtual Energy System for Carbon-Efficient Applications*. ASPLOS 2023.
6. Clark, Fraser, Hand, Hansen, Jul, Limpach, Pratt, Warfield. *Live Migration of Virtual Machines*. NSDI 2005.
7. Radovanović et al. *Carbon-Aware Computing for Datacenters*. IEEE Trans. Power Systems 2022.

Supporting: Aslan, Mayers, Koomey, France. *Electricity Intensity of Internet Data Transmission*.
J. Industrial Ecology 2018 (kWh/GB parameter). Schlömer et al., IPCC AR5 WG3 Annex III (lifecycle
emission factors used to convert generation mix to CI).
