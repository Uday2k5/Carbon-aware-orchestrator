"""Rolling-origin backtest: MAE / MAPE per horizon step."""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
import pandas as pd

from .models import Forecaster, GradientBoostingForecaster, PersistenceForecaster, SeasonalNaiveForecaster


def backtest(
    factory: Callable[[], Forecaster],
    series,
    horizon: int = 24,
    n_origins: int = 20,
    min_train: int = 24 * 14,
) -> pd.DataFrame:
    s = series if isinstance(series, pd.Series) else pd.Series(np.asarray(series, float))
    n = len(s)
    if n < min_train + horizon + 1:
        raise ValueError(f"series too short ({n}); need >= {min_train + horizon + 1}")
    origins = np.linspace(min_train, n - horizon - 1, n_origins).astype(int)
    errs = np.zeros((n_origins, horizon))
    pct = np.zeros((n_origins, horizon))
    name = None
    for i, o in enumerate(origins):
        hist = s.iloc[: o + 1]
        truth = s.values[o + 1: o + 1 + horizon]
        m = factory().fit(hist)
        name = name or m.name
        pred = m.predict(hist, horizon)
        errs[i] = np.abs(pred - truth)
        pct[i] = np.abs(pred - truth) / np.maximum(np.abs(truth), 1.0)
    return pd.DataFrame({
        "model": name,
        "h": np.arange(1, horizon + 1),
        "mae": errs.mean(axis=0),
        "mape_pct": 100 * pct.mean(axis=0),
    })


def compare_models(series, horizon: int = 24, n_origins: int = 20, min_train: int = 24 * 14,
                   include_xgboost: bool = False) -> pd.DataFrame:
    factories = {
        "persistence": lambda: PersistenceForecaster(),
        "seasonal-naive": lambda: SeasonalNaiveForecaster(24),
        "gradient-boosting[sklearn]": lambda: GradientBoostingForecaster("sklearn", horizon),
    }
    if include_xgboost:
        factories["gradient-boosting[xgboost]"] = lambda: GradientBoostingForecaster("xgboost", horizon)
    frames = [backtest(f, series, horizon, n_origins, min_train) for f in factories.values()]
    df = pd.concat(frames, ignore_index=True)
    summary = df.groupby("model")[["mae", "mape_pct"]].mean().sort_values("mae")
    summary.attrs["per_horizon"] = df
    return summary
