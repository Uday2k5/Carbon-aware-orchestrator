"""EXP-06  How good is the carbon forecaster, and does it over- or under-fit?

Walk-forward test on the live store (run `cao live tick` first): for each of the last four weeks a
model is trained only on data before that week, then asked for 24 h forecasts four times a day.

    python experiments/exp06_forecaster_study.py [--site site] [--weeks 4]

Compared, per grid:
    same as now / same hour yesterday      the naive baselines
    old trees                              the first version: default boosted trees, no weather
    final, no weather                      final design without the weather inputs (ablation)
    final                                  regularised weather-driven trees + blend (what runs live)
"""
import argparse
import warnings

import numpy as np
import pandas as pd

from _common import RESULTS
from cao.forecast.models import GradientBoostingForecaster
from cao.forecast.weather_blend import WeatherBlendForecaster

warnings.filterwarnings("ignore")
ap = argparse.ArgumentParser()
ap.add_argument("--site", default="site")
ap.add_argument("--weeks", type=int, default=4)
args = ap.parse_args()

ci = pd.read_csv(f"{args.site}/data/ci_hourly.csv", parse_dates=["timestamp"]).set_index("timestamp")
wxw = pd.read_csv(f"{args.site}/data/weather_hourly.csv", parse_dates=["timestamp"]).set_index("timestamp")
rows = []
for loc in ci.columns:
    s = ci[loc].dropna()
    wx = wxw[[c for c in wxw.columns if c.startswith(loc + "|")]].copy()
    wx.columns = [c.split("|")[1] for c in wx.columns]
    end = s.index.max().floor("D")
    err = {k: [] for k in ("same as now", "same hour yesterday", "old trees", "final, no weather", "final")}
    fit_gap = []
    for f in range(args.weeks):
        fs = end - pd.Timedelta(days=7 * (args.weeks - f))
        hist0 = s[s.index < fs]
        if len(hist0) < 24 * 28:
            continue
        old = GradientBoostingForecaster(max_horizon=24, holdout_frac=0.0, target="delta").fit(hist0)
        final = WeatherBlendForecaster().fit(hist0, wx)
        plain = WeatherBlendForecaster().fit(hist0)
        fit_gap.append((final.diag["train_mae"], final.diag["val_mae_trees"], final.diag["val_mae"]))
        for o in pd.date_range(fs - pd.Timedelta(hours=1), fs + pd.Timedelta(days=7) - pd.Timedelta(hours=2), freq="6h"):
            y = s.reindex(pd.date_range(o + pd.Timedelta(hours=1), periods=24, freq="1h")).values
            h = s[s.index <= o]
            if np.isnan(y).any() or h.index[-1] != o:
                continue
            p = final.predict_parts(h, wx)
            err["final"].append(np.abs(p["p50"] - y))
            err["same as now"].append(np.abs(p["persistence"] - y))
            err["same hour yesterday"].append(np.abs(p["seasonal"] - y))
            err["final, no weather"].append(np.abs(plain.predict(h) - y))
            err["old trees"].append(np.abs(old.predict(h, 24) - y))
    if not err["final"]:
        continue
    m = {k: float(np.mean(v)) for k, v in err.items()}
    naive = min(m["same as now"], m["same hour yesterday"])
    g = np.mean(fit_gap, axis=0)
    rows.append({"grid": loc, "forecasts": len(err["final"]), **{k: round(v, 1) for k, v in m.items()},
                 "skill vs best naive %": round((1 - m["final"] / naive) * 100, 1),
                 "trained-on days": round(g[0], 1), "held-out days (trees)": round(g[1], 1), "held-out days (blend)": round(g[2], 1)})
out = pd.DataFrame(rows).set_index("grid")
pd.set_option("display.width", 240); pd.set_option("display.max_columns", 30)
print("Mean error (gCO2/kWh), 24 h ahead, last", args.weeks, "weeks, models never saw the week they are scored on:\n")
print(out[["forecasts", "same as now", "same hour yesterday", "old trees", "final, no weather", "final", "skill vs best naive %"]].to_string())
print("\nGeneralisation of the final model (error of the predicted change):\n")
print(out[["trained-on days", "held-out days (trees)", "held-out days (blend)", "final"]].rename(columns={"final": "unseen test weeks"}).to_string())
out.to_csv(RESULTS / "exp06_forecaster_study.csv")
print(f"\n-> {RESULTS}/exp06_forecaster_study.csv")
