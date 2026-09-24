"""EXP-03  How much carbon does forecast error cost?  (regret vs oracle as sigma grows)"""
import pandas as pd

from _common import RESULTS, load_cost_model, load_settings
from cao.carbon.schema import strip_index, to_traces
from cao.carbon.sources.synthetic import generate_dataset
from cao.simulator import MigrationAwarePolicy, NoisyForecast, PersistenceForecast, SeasonalNaiveForecast, compare_policies, generate_jobs, oracle

settings = load_settings()
cm = load_cost_model(settings)
traces = strip_index(to_traces(generate_dataset(settings.region_names, days=7, seed=0), hours=24 * 7))
jobs = generate_jobs(20, list(traces), horizon_h=float(24 * 7), seed=0)

rows = []
providers = [("oracle", None)] + [(f"noisy-{s:.2f}", NoisyForecast(traces, s, 0)) for s in (0.05, 0.1, 0.2, 0.3, 0.5)]
providers += [("persistence", PersistenceForecast(traces)), ("seasonal-naive", SeasonalNaiveForecast(traces))]
for name, fp in providers:
    pol = oracle(MigrationAwarePolicy(), traces) if fp is None else MigrationAwarePolicy(forecast=fp, name=f"migration-aware[{name}]")
    df = compare_policies(traces, jobs, [pol], cm, latency_ms=settings.latency_ms, capacity=settings.capacity_cpu)
    r = df.iloc[0].to_dict()
    r["forecast"] = name
    rows.append(r)
out = pd.DataFrame(rows)
ref = out.loc[out["forecast"] == "oracle", "total_g"].iloc[0]
out["regret_g"] = (out["total_g"] - ref).round(1)
print(out[["forecast", "total_g", "migration_g", "migrations", "deadline_violations", "regret_g"]].to_string(index=False))
out.to_csv(RESULTS / "exp03_forecast_sensitivity.csv", index=False)
print(f"\n-> {RESULTS}/exp03_forecast_sensitivity.csv")
