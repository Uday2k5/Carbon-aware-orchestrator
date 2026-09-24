"""EXP-01  The tiny experiment that everything else is built around.

    200 MB job -> measured migration energy -> compare two grids -> payback time -> MOVE/REFUSE

Sweeps state size x remaining runtime and writes the MOVE/REFUSE grid (Carbon Payback
Boundary).  Uses config/migration_model.json when `cao profile` + `cao fit` have run,
otherwise the YAML placeholders (clearly labelled).
"""
import numpy as np
import pandas as pd

from _common import RESULTS, load_cost_model, load_settings
from cao.core.models import Job
from cao.decision.payback import payback_boundary
from cao.decision.simple import decide_simple

settings = load_settings()
cm = load_cost_model(settings)
print(f"cost model: {cm.source} | network {cm.network_kwh_per_gb} kWh/GB ({cm.network_ci_attribution})\n")

CI_SRC, CI_DST, POWER = 650.0, 50.0, 0.2   # India -> Sweden, 200 W job

print("== Plan examples ==")
for jid, state, rem in (("Job A", 0.2, 2.0), ("Job B", 60.0, 0.5)):
    job = Job(jid, "ml-training", POWER, rem, state, "india", running=True, started=True)
    d = decide_simple(job, {"india": CI_SRC, "sweden": CI_DST}, cm)
    print(f"{jid}: state {state:5.1f} GB, remaining {rem:3.1f} h -> {d.action.value:6}  "
          f"saved {d.saved_g:7.1f} g, migration {d.migration_g:7.1f} g, payback {d.payback_h:.2f} h")

print("\n== Carbon Payback Boundary (min remaining hours for MOVE) ==")
sizes = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 60]
pts = payback_boundary(POWER, CI_SRC, CI_DST, sizes, cm)
bdf = pd.DataFrame([p.__dict__ for p in pts])
print(bdf.round(2).to_string(index=False))
bdf.to_csv(RESULTS / "exp01_payback_boundary.csv", index=False)

print("\n== MOVE/REFUSE grid: rows = state GB, cols = remaining hours ==")
remaining = [0.25, 0.5, 1, 2, 4, 8, 12, 24]
grid = pd.DataFrame(index=sizes, columns=remaining, dtype=object)
for s in sizes:
    for r in remaining:
        job = Job("g", "ml-training", POWER, r, s, "india", running=True, started=True)
        grid.loc[s, r] = decide_simple(job, {"india": CI_SRC, "sweden": CI_DST}, cm).action.value[0]
print(grid.to_string())
grid.to_csv(RESULTS / "exp01_move_refuse_grid.csv")

print("\n== Sensitivity: payback hours for a 5 GB job vs CI gap ==")
rows = []
for gap in (50, 100, 200, 400, 600):
    p = payback_boundary(POWER, CI_DST + gap, CI_DST, [5.0], cm)[0]
    rows.append({"ci_gap_g_per_kwh": gap, "migration_g": round(p.migration_g, 1), "payback_h": round(p.payback_h, 2)})
print(pd.DataFrame(rows).to_string(index=False))
print(f"\n-> {RESULTS}/exp01_*.csv")
