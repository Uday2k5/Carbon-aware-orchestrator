"""EXP-07  What is the trained forecast worth to the scheduler, and which scheduler uses it better?

Same jobs, same real grid data (run `cao live tick` first), three forecasts handed to the scheduler:
    naive      "same as now"
    model      our forecaster; each hour uses a model trained only on data before that week
    perfect    the true future (upper bound on what any forecast could give)
and two schedulers: the payback rule (greedy) and the 24 h MILP plan.

    python experiments/exp07_forecast_value.py [--site site] [--days 28] [--streams 2]

Slow: the MILP re-plans every two hours, so 28 days x 2 job streams takes about half an hour.
New jobs stop two days before the end so every variant finishes the same work.
"""
import argparse
import time
import warnings

import numpy as np
import pandas as pd

from _common import RESULTS
from cao.forecast.weather_blend import WeatherBlendForecaster
from cao.live.config import load_live_config
from cao.live.pipeline import _default_cost_model
from cao.live.twin import sample_arrivals, service_jobs
from cao.simulator.forecast_providers import ForecastProvider, OracleForecast, PersistenceForecast
from cao.simulator.policies import MigrationAwarePolicy, MilpPolicy
from cao.simulator.sim import run_simulation

warnings.filterwarnings("ignore")
ap = argparse.ArgumentParser()
ap.add_argument("--site", default="site")
ap.add_argument("--days", type=int, default=28)
ap.add_argument("--streams", type=int, default=2)
args = ap.parse_args()

cfg, cm = load_live_config(), _default_cost_model()
ci = pd.read_csv(f"{args.site}/data/ci_hourly.csv", parse_dates=["timestamp"]).set_index("timestamp").interpolate(limit=3).ffill()
wxw = pd.read_csv(f"{args.site}/data/weather_hourly.csv", parse_dates=["timestamp"]).set_index("timestamp")
locs = list(ci.columns)
end = ci.index.max().floor("D")
start = end - pd.Timedelta(days=args.days)
hours = pd.date_range(start, end - pd.Timedelta(hours=1), freq="1h")

# ---- what our model would have issued at every hour (weekly refit, never trained on the week it forecasts)
t0 = time.time()
issued = {c: [] for c in locs}
for c in locs:
    s = ci[c].dropna()
    wx = wxw[[k for k in wxw.columns if k.startswith(c + "|")]].copy()
    wx.columns = [k.split("|")[1] for k in wx.columns]
    weeks = range((args.days + 6) // 7)
    models = [(start + pd.Timedelta(days=7 * w), WeatherBlendForecaster().fit(s[s.index < start + pd.Timedelta(days=7 * w)], wx)) for w in weeks]
    for h in hours:
        m = [mm for (b0, mm) in models if b0 <= h][-1]
        p = m.predict_parts(s[s.index <= h], wx, 24, explain=False)
        issued[c].append(np.concatenate([[float(s.loc[h])], p["p50"][:23]]))
print(f"forecasts ready ({time.time() - t0:.0f} s)", flush=True)


class ModelForecast(ForecastProvider):
    def forecast(self, region, t, horizon):
        return issued[region][min(t, len(hours) - 1)][:horizon]


traces = {c: ci[c].reindex(hours).values.astype(float) for c in locs}
lat = {a: {b: cfg.latency_ms[a][b] for b in locs} for a in locs}
cap = {c: cfg.capacity_cpu for c in locs}
rows = []
for stream in range(args.streams):
    jobs = service_jobs(cfg, locs, 0.0)
    for i, h in enumerate(hours[: (args.days - 2) * 24]):
        jobs += sample_arrivals(h + pd.Timedelta(days=400 * stream), float(i), locs, cfg.arrival_rate)
    for name, fc in (("naive", PersistenceForecast(traces)), ("model", ModelForecast()), ("perfect", OracleForecast(traces))):
        greedy = run_simulation(traces, jobs, MigrationAwarePolicy(), cm, lat, cap, forecast=fc)
        planner = MilpPolicy(time_limit_s=6, replan_every=2)
        milp = run_simulation(traces, jobs, planner, cm, lat, cap, forecast=fc)
        rows.append({"stream": stream, "forecast": name, "greedy_g": greedy.total_g, "milp_g": milp.total_g,
                     "greedy_late": greedy.deadline_violations, "milp_late": milp.deadline_violations, "milp_fallbacks": planner.fallbacks})
        print(f"stream {stream} {name:<8} greedy {greedy.total_g:>8.0f} g   MILP {milp.total_g:>8.0f} g   ({time.time() - t0:.0f} s)", flush=True)

df = pd.DataFrame(rows)
df.to_csv(RESULTS / "exp07_forecast_value.csv", index=False)
mean = df.groupby("forecast")[["greedy_g", "milp_g"]].mean()
print(f"\n{args.days} days ({start:%d %b} to {end:%d %b %Y}), {args.streams} job streams, {len(locs)} grids")
for col, label in (("greedy_g", "payback rule"), ("milp_g", "24 h MILP  ")):
    n, m, p = mean.loc["naive", col], mean.loc["model", col], mean.loc["perfect", col]
    print(f"{label}: naive {n:,.0f} g   model {m:,.0f} g ({(1 - m / n) * 100:.1f} % lower)   perfect {p:,.0f} g ({(1 - p / n) * 100:.1f} % lower)"
          f"   model captures {(n - m) / (n - p) * 100:.0f} % of the possible gain")
