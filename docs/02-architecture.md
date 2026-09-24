# Architecture

## Components

| component | code | input | output |
| --- | --- | --- | --- |
| Carbon data | `cao/carbon` | APIs / csv | `timestamp, region, ci_g_per_kwh, source` (hourly UTC) |
| Forecaster | `cao/forecast` | CI history per region | 24 h point forecast + interval |
| Energy meter | `cao/energy` | psutil samples / RAPL / Kepler | Joules per phase / per pod |
| Migration profiler | `cao/migration/profiler.py` | state sizes | checkpoint / transfer / restore s & J |
| Cost model | `cao/migration/cost_model.py` | fitted a, b, kWh/GB | migration gCO2e for (S, CI_src, CI_dst) |
| Decision engine | `cao/decision` | jobs, CI forecast, cost model, latency | MOVE / WAIT / HOLD / REFUSE |
| Simulator | `cao/simulator` | traces, jobs, policy | total gCO2e, migrations, violations, regret |
| Controller | `cao/k8s` | managed pods + node labels | nodeSelector patches, telemetry |
| Store | `cao/db` | everything above | sqlite |
| Dashboard | `cao/dashboard` | sqlite + results csv | charts |
| Replay | `cao/replay` | simulator timeline (`record_timeline=True`) | replay.json → self-contained HTML page, GIF/MP4 |

## Data flow (one controller tick)

```
list pods (label carbon-aware.io/managed=true)
  └─ node label topology.carbon-aware.io/region → job.region
  └─ annotations → power_kw, state_gb, remaining_h, deadline, user_region, sla_rtt_ms
CI provider → {region: [ci_now, ci_+1h, ..., ci_+23h]}
DecisionEngine.decide(jobs, ci, now)
  ├─ feasible_regions(job)              SLA + movable
  ├─ pending & preemptible → best (region, start) over forecast → WAIT / start
  ├─ running → decide_simple: max net saving; MOVE if net > margin else REFUSE / HOLD
  └─ mode=milp → solve_milp → plan_to_decisions
MOVE → migrate(): patch Deployment nodeSelector → old pod SIGTERM → checkpoint →
       new pod on target region → restore → Ready; record downtime
decisions / migrations → sqlite
```

## Migration sequence on the testbed

```
controller            api-server          old pod (india)        new pod (sweden)      /checkpoints
    │ patch nodeSelector  │                    │                       │                   │
    │────────────────────►│  SIGTERM           │                       │                   │
    │                     │───────────────────►│ checkpoint(state)     │                   │
    │                     │                    │──────────────────────────────────────────►│ state.bin
    │                     │                    │ exit 0                │                   │ metrics.json
    │                     │ schedule           │                       │                   │
    │                     │───────────────────────────────────────────►│ restore(state)    │
    │                     │                    │                       │◄──────────────────│
    │ wait_for_ready ◄────│ Ready              │                       │                   │
    │ total_s = downtime; checkpoint_s from metrics.json
```

All k3d nodes mount the same host directory at `/checkpoints`, so the *transfer* on the
testbed is a local disk path. The network cost of a real inter-region transfer is therefore
measured separately by the profiler (`--transport loopback`, optionally shaped with `tc netem`)
and modelled as `bytes × kWh/GB` in the cost model. State this clearly in the report.

## Emulated regions

One laptop, one real grid. Each k3d agent is a *logical* region whose CI trace is replayed
from real data (ENTSO-E / EIA / UK ESO / Electricity Maps). Workload energy and migration
cost are measured locally; carbon = measured kWh × replayed CI.

## Replay export (`cao/replay/export.py`)

`run_simulation(..., record_timeline=True)` stores one snapshot per hour (status, region, applied
action, progress of every job, cumulative carbon). `build_replay()` packs all policies of a
`compare_policies()` run into one JSON (status codes 0 not-released / 1 pending / 2 running /
3 suspended / 4 done; actions M/W/H/R; regions as indices) plus the CI traces, job table,
MOVE/WAIT/REFUSE events and a payback-boundary grid for the two most extreme regions.
`render_html()` embeds that JSON into `template.html`; `render_animation()` draws the same scene
with matplotlib.
