"""EXP-04  The payback boundary depends on the assumed network energy intensity (kWh/GB).
Literature spans ~0.004 (core network only) to 0.06 (Aslan et al. 2018, incl. access).
"""
import copy

import pandas as pd

from _common import RESULTS, load_cost_model, load_settings
from cao.carbon.schema import strip_index, to_traces
from cao.carbon.sources.synthetic import generate_dataset
from cao.decision.payback import payback_boundary
from cao.simulator import GreenestRegionPolicy, MigrationAwarePolicy, NoisyForecast, compare_policies, generate_jobs

settings = load_settings()
base = load_cost_model(settings)
traces = strip_index(to_traces(generate_dataset(settings.region_names, days=5, seed=0), hours=24 * 5))
jobs = generate_jobs(16, list(traces), horizon_h=float(24 * 5), seed=0)

rows = []
for kwh_per_gb in (0.0, 0.004, 0.01, 0.03, 0.06, 0.1):
    cm = copy.deepcopy(base)
    cm.network_kwh_per_gb = kwh_per_gb
    pb = {p.state_gb: round(p.payback_h, 2) for p in payback_boundary(0.2, 650, 50, [1, 10, 60], cm)}
    df = compare_policies(traces, jobs, [GreenestRegionPolicy(), MigrationAwarePolicy()], cm,
                          latency_ms=settings.latency_ms, forecast=NoisyForecast(traces, 0.1))
    g = df.set_index("policy")
    rows.append({
        "network_kwh_per_gb": kwh_per_gb,
        "payback_h_1gb": pb[1], "payback_h_10gb": pb[10], "payback_h_60gb": pb[60],
        "greenest_total_g": g.loc["greenest-region", "total_g"],
        "greenest_migrations": g.loc["greenest-region", "migrations"],
        "aware_total_g": g.loc["migration-aware", "total_g"],
        "aware_migrations": g.loc["migration-aware", "migrations"],
    })
out = pd.DataFrame(rows)
print(out.to_string(index=False))
out.to_csv(RESULTS / "exp04_network_energy_sensitivity.csv", index=False)
print(f"\n-> {RESULTS}/exp04_network_energy_sensitivity.csv")
