"""Forecasting on the live store: one weather-driven model per grid, honest fallbacks while a grid
has too little history, a daily walk-forward backtest, and a study of what the forecast is worth
to the scheduler (naive forecast vs our model vs perfect foresight on the same week of real data).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..forecast.models import SeasonalNaiveForecaster
from ..forecast.weather_blend import MIN_HOURS, WeatherBlendForecaster

MIN_SEASONAL_HOURS = 48
ISO = "%Y-%m-%dT%H:%M:%SZ"
H1 = pd.Timedelta(hours=1)


def contiguous_tail(series: pd.Series) -> pd.Series:
    """Last unbroken run of non-missing hourly values."""
    s = series.dropna()
    if s.empty:
        return s
    gaps = s.index.to_series().diff() > H1
    if gaps.any():
        s = s[s.index >= gaps[gaps].index[-1]]
    return s


def _fit_one(series: pd.Series, wx: Optional[pd.DataFrame]) -> Optional[WeatherBlendForecaster]:
    if len(series) < MIN_HOURS:
        return None
    try:
        return WeatherBlendForecaster().fit(series, wx)
    except Exception:
        return None


def fit_models(wide: pd.DataFrame, weather: Dict[str, pd.DataFrame], upto: pd.Timestamp) -> Dict[str, Optional[WeatherBlendForecaster]]:
    """One model per location on data up to and including `upto` (None while history is too short)."""
    out = {}
    for loc in wide.columns:
        s = contiguous_tail(wide[loc][wide.index <= upto])
        if len(s):
            out[loc] = _fit_one(s, weather.get(loc))
    return out


def predict(models: Dict[str, object], wide: pd.DataFrame, weather: Dict[str, pd.DataFrame], at: pd.Timestamp,
            horizon: int = 24, explain: bool = True) -> Dict[str, dict]:
    """Forecast hours at+1 .. at+horizon for every location with data at `at`."""
    out = {}
    for loc, m in models.items():
        s = contiguous_tail(wide[loc][wide.index <= at])
        if s.empty:
            continue
        if m is not None and len(s) >= 200:
            parts = m.predict_parts(s, weather.get(loc), horizon)
            out[loc] = {"model": "weather-trees" if m.diag.get("has_weather") else "trees", "p50": parts["p50"], "lo": parts["lo"],
                        "hi": parts["hi"], "weather_effect": parts["weather_effect"] if explain else None}
        elif len(s) >= MIN_SEASONAL_HOURS:
            out[loc] = {"model": "seasonal", "p50": np.asarray(SeasonalNaiveForecaster(24).predict(s.values, horizon), float),
                        "lo": None, "hi": None, "weather_effect": None}
        else:
            out[loc] = {"model": "persistence", "p50": np.full(horizon, float(s.values[-1])), "lo": None, "hi": None, "weather_effect": None}
    return out


def daily_backtest(wide: pd.DataFrame, weather: Dict[str, pd.DataFrame], last_complete: pd.Timestamp, days: int = 14,
                   refit_days: int = 2, keep_models: bool = False):
    """Walk-forward test on the last `days` complete UTC days.

    A model is refit every `refit_days` on data strictly before its block, then asked for a 24 h
    forecast four times a day.  Returns per-location errors for ours and both naive baselines,
    error by hours-ahead, and the last scored day as a curve.  With keep_models the per-block
    models are returned too (used by the forecast-value study).
    """
    res: Dict[str, dict] = {}
    blocks: Dict[str, list] = {}
    day0 = (last_complete + H1).floor("D")
    for loc in wide.columns:
        s_all = wide[loc]
        wx = weather.get(loc)
        e_ours, e_pers, e_seas = [], [], []          # each entry: array(24) of abs errors
        inside, width = [], []
        last_curve = None
        n_days_scored = set()
        for start_k in range(days, 0, -refit_days):
            b_start = day0 - pd.Timedelta(days=start_k)
            hist0 = contiguous_tail(s_all[s_all.index < b_start])
            m = _fit_one(hist0, wx)
            if m is None:
                continue
            blocks.setdefault(loc, []).append((b_start, min(b_start + pd.Timedelta(days=refit_days), day0), m))
            for k in range(start_k, max(start_k - refit_days, 0), -1):
                d = day0 - pd.Timedelta(days=k)
                for off in (0, 6, 12, 18):
                    origin = d + pd.Timedelta(hours=off) - H1
                    tgt = pd.date_range(origin + H1, periods=24, freq="1h")
                    y = s_all.reindex(tgt).values.astype(float)
                    hist = contiguous_tail(s_all[s_all.index <= origin])
                    if np.isnan(y).any() or len(hist) < MIN_HOURS or hist.index[-1] != origin:
                        continue
                    parts = m.predict_parts(hist, wx, 24)
                    e_ours.append(np.abs(parts["p50"] - y)); e_pers.append(np.abs(parts["persistence"] - y)); e_seas.append(np.abs(parts["seasonal"] - y))
                    inside.append((y >= parts["lo"]) & (y <= parts["hi"])); width.append(parts["hi"] - parts["lo"])
                    n_days_scored.add(d)
                    if off == 0:
                        last_curve = {"day": d.strftime("%Y-%m-%d"), "ts": [t.strftime(ISO) for t in tgt],
                                      "actual": [round(float(v), 1) for v in y], "ours": [round(float(v), 1) for v in parts["p50"]],
                                      "persistence": [round(float(v), 1) for v in parts["persistence"]]}
        if not e_ours:
            continue
        eo, ep, es = np.array(e_ours), np.array(e_pers), np.array(e_seas)
        naive = min(float(ep.mean()), float(es.mean()))
        res[loc] = {
            "n_days": len(n_days_scored), "n_forecasts": int(len(eo)),
            "mae_ours": round(float(eo.mean()), 1), "mae_persistence": round(float(ep.mean()), 1), "mae_seasonal": round(float(es.mean()), 1),
            "skill_pct": round((1 - float(eo.mean()) / naive) * 100, 1) if naive > 0 else 0.0,
            "band_hit_pct": round(float(np.mean(inside)) * 100, 1), "band_width": round(float(np.mean(width)), 1),
            "by_horizon": {"ours": [round(float(v), 1) for v in eo.mean(axis=0)], "persistence": [round(float(v), 1) for v in ep.mean(axis=0)]},
            "last_day": last_curve,
        }
    return (res, blocks) if keep_models else res


def hourly_block_forecasts(wide: pd.DataFrame, weather: Dict[str, pd.DataFrame], blocks: Dict[str, list], hours: pd.DatetimeIndex) -> Dict[str, list]:
    """For every hour, the forecast the model that existed at that hour would have issued (None where no model existed)."""
    table: Dict[str, list] = {}
    for c, bl in blocks.items():
        s_all, out = wide[c], []
        for h in hours:
            m = next((mm for (b0, b1, mm) in bl if b0 <= h < b1), None)
            if m is None and bl and h >= bl[-1][1]:
                m = bl[-1][2]                      # hours after the last block: its model is still strictly older than them
            hist = contiguous_tail(s_all[s_all.index <= h])
            if m is None or len(hist) < MIN_HOURS or hist.index[-1] != h:
                out.append(None)
            else:
                p = m.predict_parts(hist, weather.get(c), 24, explain=False)
                out.append({"p50": p["p50"], "lo": p["lo"], "hi": p["hi"], "model": "weather-trees" if m.diag.get("has_weather") else "trees"})
        table[c] = out
    return table


def forecast_value_study(cfg, cost_model, wide: pd.DataFrame, hours: pd.DatetimeIndex, table: Dict[str, list],
                         drain_days: int = 2, streams: int = 3) -> Optional[dict]:
    """What is the forecast worth to the scheduler?  Same real grid data, same jobs, same payback-aware
    rule, three forecasts: naive (same as now), our model (each hour forecast by the model that
    existed then), perfect foresight.  Jobs stop arriving `drain_days` before the end so every variant
    finishes the same work, and the result is averaged over several independent job streams."""
    from ..simulator.forecast_providers import ForecastProvider, OracleForecast, PersistenceForecast
    from ..simulator.policies import CarbonUnawarePolicy, MigrationAwarePolicy
    from ..simulator.sim import run_simulation
    from .twin import sample_arrivals, service_jobs

    carried = wide.ffill()
    locs = [c for c in wide.columns if c in table and carried[c].reindex(hours).notna().all()]
    arrive = len(hours) - drain_days * 24
    if len(locs) < 2 or arrive < 24:
        return None
    traces = {c: carried[c].reindex(hours).values.astype(float) for c in locs}
    fc = {c: [np.full(24, traces[c][i]) if p is None else np.concatenate([[traces[c][i]], p["p50"][:23]]) for i, p in enumerate(table[c])] for c in locs}

    class TableForecast(ForecastProvider):
        name = "our model"

        def forecast(self, region, t, horizon):
            return fc[region][min(t, len(hours) - 1)][:horizon]

    lat = {a: {b: cfg.latency_ms[a][b] for b in locs} for a in locs}
    cap = {c: cfg.capacity_cpu for c in locs}
    tot = {"naive": [], "model": [], "perfect": [], "unaware": []}
    late = {"naive": 0, "model": 0, "perfect": 0}
    n_jobs = 0
    for k in range(streams):
        jobs = service_jobs(cfg, locs, 0.0)
        for i, h in enumerate(hours[:arrive]):
            jobs += sample_arrivals(h + pd.Timedelta(days=400 * k), float(i), locs, cfg.arrival_rate)   # shifted seed = another job stream
        n_jobs += len(jobs)
        run = lambda pol, f: run_simulation(traces, jobs, pol, cost_model, lat, cap, forecast=f)
        res = {"naive": run(MigrationAwarePolicy(), PersistenceForecast(traces)), "model": run(MigrationAwarePolicy(), TableForecast()),
               "perfect": run(MigrationAwarePolicy(), OracleForecast(traces)), "unaware": run(CarbonUnawarePolicy(), OracleForecast(traces))}
        for key, r in res.items():
            tot[key].append(r.total_g)
            if key in late:
                late[key] += r.deadline_violations
    m = {key: float(np.mean(v)) for key, v in tot.items()}
    gain = m["naive"] - m["perfect"]
    return {
        "days": arrive // 24, "streams": streams, "from": hours[0].strftime(ISO), "to": hours[arrive - 1].strftime(ISO),
        "jobs": n_jobs, "grids": locs, "naive_g": round(m["naive"], 1), "model_g": round(m["model"], 1), "perfect_g": round(m["perfect"], 1),
        "unaware_g": round(m["unaware"], 1), "saved_by_model_g": round(m["naive"] - m["model"], 1),
        "saved_pct": round((1 - m["model"] / m["naive"]) * 100, 2) if m["naive"] > 0 else None,
        "perfect_pct": round((1 - m["perfect"] / m["naive"]) * 100, 2) if m["naive"] > 0 else None,
        "captured_pct": round((m["naive"] - m["model"]) / gain * 100, 1) if gain > 1e-6 else None, "deadline_missed": late,
    }
