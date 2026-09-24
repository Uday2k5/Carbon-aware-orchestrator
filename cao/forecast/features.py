"""Feature engineering for 24 h carbon-intensity forecasting (direct multi-horizon)."""
from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import numpy as np
import pandas as pd

LAGS: Tuple[int, ...] = (1, 2, 3, 6, 12, 24, 48, 168)


def _as_series(x) -> pd.Series:
    if isinstance(x, pd.Series):
        return x.astype(float)
    return pd.Series(np.asarray(x, dtype=float))


def make_features(series, lags: Sequence[int] = LAGS) -> pd.DataFrame:
    """Per-timestamp features. Calendar features come from a DatetimeIndex when present,
    otherwise from the position (hourly assumption)."""
    s = _as_series(series)
    idx = s.index
    f = pd.DataFrame(index=idx)
    if isinstance(idx, pd.DatetimeIndex):
        f["hour"] = idx.hour
        f["dow"] = idx.dayofweek
        f["month"] = idx.month
    else:
        pos = np.arange(len(s))
        f["hour"] = pos % 24
        f["dow"] = (pos // 24) % 7
        f["month"] = 0
    f["hour_sin"] = np.sin(2 * np.pi * f["hour"] / 24)
    f["hour_cos"] = np.cos(2 * np.pi * f["hour"] / 24)
    f["ci"] = s.values
    for lag in lags:
        f[f"lag_{lag}"] = s.shift(lag).values
    f["roll_mean_24"] = s.rolling(24, min_periods=1).mean().values
    f["roll_std_24"] = s.rolling(24, min_periods=2).std().values
    f["roll_mean_168"] = s.rolling(168, min_periods=1).mean().values
    # early rows: fill missing lags with the earliest known value
    f = f.bfill().ffill()
    return f


def make_supervised(
    series, horizons: Iterable[int] = range(1, 25), lags: Sequence[int] = LAGS
) -> Tuple[pd.DataFrame, np.ndarray]:
    """Stack (features(t), h) -> ci(t+h) rows for all horizons."""
    s = _as_series(series)
    feats = make_features(s, lags)
    vals = s.values
    n = len(s)
    xs, ys = [], []
    for h in horizons:
        if h >= n:
            continue
        x = feats.iloc[: n - h].copy()
        x["h"] = h
        xs.append(x)
        ys.append(vals[h:])
    if not xs:
        raise ValueError("series too short for requested horizons")
    X = pd.concat(xs, ignore_index=True)
    y = np.concatenate(ys)
    return X, y
