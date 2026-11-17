"""Forecasting on the live hourly store.

Candidates per location: boosted trees on the change from now ("gbm"), seasonal-naive,
persistence, and their average ("blend").  Once a day a walk-forward backtest scores every
candidate on each of the last 14 days (model refit on data before the day), picks for each
day the candidate that did best over the *previous* week, and reports that selector's
out-of-sample error.  The candidate that did best over the last week serves today's forecast.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..forecast.models import GradientBoostingForecaster, SeasonalNaiveForecaster

MIN_GB_HOURS = 240      # 10 days of hourly history before the boosted model is used
MIN_SEASONAL_HOURS = 48
CANDIDATES = ("gbm", "seasonal", "persistence", "blend")
ISO = "%Y-%m-%dT%H:%M:%SZ"


def contiguous_tail(series: pd.Series) -> pd.Series:
    """Last unbroken run of non-missing hourly values."""
    s = series.dropna()
    if s.empty:
        return s
    gaps = s.index.to_series().diff() > pd.Timedelta(hours=1)
    if gaps.any():
        s = s[s.index >= gaps[gaps].index[-1]]
    return s


def _gbm() -> GradientBoostingForecaster:
    return GradientBoostingForecaster(max_horizon=24, holdout_frac=0.0, target="delta", params={"max_iter": 200})


def _candidates(model, hist: pd.Series, horizon: int = 24) -> Dict[str, np.ndarray]:
    v = hist.values.astype(float)
    out = {"persistence": np.full(horizon, v[-1])}
    out["seasonal"] = np.asarray(SeasonalNaiveForecaster(24).predict(v, horizon), float) if len(v) >= MIN_SEASONAL_HOURS else out["persistence"]
    if model is not None and len(v) >= 170:
        out["gbm"] = np.asarray(model.predict(hist, horizon), float)
        out["blend"] = (out["gbm"] + out["seasonal"] + out["persistence"]) / 3.0
    return out


def fit_models(wide: pd.DataFrame, upto: pd.Timestamp) -> Dict[str, Optional[GradientBoostingForecaster]]:
    """One boosted model per location on data up to and including `upto` (None when history is short)."""
    models = {}
    for loc in wide.columns:
        s = contiguous_tail(wide[loc][wide.index <= upto])
        if len(s) >= MIN_GB_HOURS:
            models[loc] = _gbm().fit(s)
        elif len(s) >= 1:
            models[loc] = None
    return models


def predict(models: Dict[str, object], wide: pd.DataFrame, at: pd.Timestamp, selection: Optional[Dict[str, str]] = None,
            bands: Optional[Dict[str, list]] = None, horizon: int = 24) -> Dict[str, dict]:
    """Forecast hours at+1 .. at+horizon per location with the selected candidate (default: gbm when available)."""
    out = {}
    for loc, m in models.items():
        s = contiguous_tail(wide[loc][wide.index <= at])
        if s.empty:
            continue
        c = _candidates(m, s, horizon)
        name = (selection or {}).get(loc) or ("gbm" if "gbm" in c else ("seasonal" if len(s) >= MIN_SEASONAL_HOURS else "persistence"))
        if name not in c:
            name = "seasonal" if len(s) >= MIN_SEASONAL_HOURS else "persistence"
        p = c[name]
        band = np.asarray(bands[loc], float) if bands and loc in bands and bands[loc] is not None else None
        out[loc] = {"model": name, "p50": p, "lo": None if band is None else np.maximum(p - band, 0.0),
                    "hi": None if band is None else p + band}
    return out


def daily_backtest(wide: pd.DataFrame, last_complete: pd.Timestamp, days: int = 14, eval_days: int = 7) -> Dict[str, dict]:
    res: Dict[str, dict] = {}
    day0 = (last_complete + pd.Timedelta(hours=1)).floor("D")       # start of the UTC day in progress
    for loc in wide.columns:
        s_all = wide[loc]
        per_day = []                                                # dicts: day, y, preds{c}
        for k in range(days, 0, -1):
            d = day0 - pd.Timedelta(days=k)
            target = s_all[(s_all.index >= d) & (s_all.index < d + pd.Timedelta(days=1))]
            hist = contiguous_tail(s_all[s_all.index < d])
            if len(target.dropna()) < 24 or len(hist) < MIN_GB_HOURS:
                continue
            preds = _candidates(_gbm().fit(hist), hist, 24)
            per_day.append({"day": d, "idx": target.index, "y": target.values.astype(float), "preds": preds})
        if len(per_day) < 2:
            continue
        n = len(per_day)
        err = {c: np.array([np.abs(pd_["preds"][c] - pd_["y"]).mean() for pd_ in per_day]) for c in CANDIDATES}
        first_eval = max(1, n - eval_days)
        chosen, ours = [], []
        for i in range(first_eval, n):
            prior = slice(max(0, i - 7), i)
            pick = min(CANDIDATES, key=lambda c: err[c][prior].mean())
            chosen.append(pick)
            ours.append(err[pick][i])
        today = min(CANDIDATES, key=lambda c: err[c][max(0, n - 7):].mean())
        abs_err = np.array([np.abs(pd_["preds"][today] - pd_["y"]) for pd_ in per_day])      # days x 24
        band = np.quantile(abs_err, 0.8, axis=0)
        band = np.convolve(np.pad(band, 1, mode="edge"), np.ones(3) / 3, mode="valid")
        last = per_day[-1]
        res[loc] = {
            "n_days": n - first_eval, "selected": today, "picked_per_day": chosen,
            "mae_ours": round(float(np.mean(ours)), 1),
            **{f"mae_{c}": round(float(err[c][first_eval:].mean()), 1) for c in CANDIDATES},
            "band": [round(float(b), 1) for b in band],
            "last_day": {"day": last["day"].strftime("%Y-%m-%d"), "model": chosen[-1],
                         "ts": [t.strftime(ISO) for t in last["idx"]],
                         "actual": [round(float(v), 1) for v in last["y"]],
                         "ours": [round(float(v), 1) for v in last["preds"][chosen[-1]]],
                         "persistence": [round(float(v), 1) for v in last["preds"]["persistence"]]},
        }
    return res
