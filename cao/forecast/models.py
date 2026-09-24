"""Forecasters with a common fit(history) / predict(history, horizon) interface."""
from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

from .features import LAGS, make_features, make_supervised


class Forecaster:
    name = "base"

    def fit(self, history) -> "Forecaster":
        return self

    def predict(self, history, horizon: int = 24) -> np.ndarray:
        raise NotImplementedError

    def predict_interval(self, history, horizon: int = 24, z: float = 1.28):
        """(lower, point, upper). Default: no uncertainty model -> point everywhere."""
        p = self.predict(history, horizon)
        return p, p, p


class PersistenceForecaster(Forecaster):
    name = "persistence"

    def predict(self, history, horizon=24):
        h = np.asarray(history, dtype=float)
        return np.full(horizon, h[-1])


class SeasonalNaiveForecaster(Forecaster):
    name = "seasonal-naive"

    def __init__(self, period: int = 24):
        self.period = period

    def predict(self, history, horizon=24):
        h = np.asarray(history, dtype=float)
        out = np.empty(horizon)
        for i in range(horizon):
            k = len(h) - self.period + (i % self.period)
            out[i] = h[k] if k >= 0 else h[-1]
        return out


class GradientBoostingForecaster(Forecaster):
    """Direct multi-horizon gradient boosting: one model, horizon as a feature.

    backend='sklearn' uses HistGradientBoostingRegressor (always available);
    backend='xgboost' uses xgboost.XGBRegressor when installed.
    """

    name = "gradient-boosting"

    def __init__(
        self,
        backend: str = "sklearn",
        max_horizon: int = 24,
        lags: Sequence[int] = LAGS,
        params: Optional[Dict] = None,
        holdout_frac: float = 0.2,
        random_state: int = 0,
    ):
        self.backend = backend
        self.max_horizon = max_horizon
        self.lags = tuple(lags)
        self.params = params or {}
        self.holdout_frac = holdout_frac
        self.random_state = random_state
        self.model = None
        self.residual_std: Dict[int, float] = {}
        self.name = f"gradient-boosting[{backend}]"

    def _make_model(self):
        if self.backend == "xgboost":
            try:
                from xgboost import XGBRegressor
            except ImportError as exc:  # pragma: no cover
                raise ImportError("pip install xgboost  (or use backend='sklearn')") from exc
            p = dict(n_estimators=400, max_depth=6, learning_rate=0.05, subsample=0.9,
                     colsample_bytree=0.9, random_state=self.random_state, n_jobs=4)
            p.update(self.params)
            return XGBRegressor(**p)
        from sklearn.ensemble import HistGradientBoostingRegressor
        p = dict(max_iter=300, learning_rate=0.06, max_depth=None, max_leaf_nodes=31,
                 l2_regularization=0.1, random_state=self.random_state)
        p.update(self.params)
        return HistGradientBoostingRegressor(**p)

    def fit(self, history):
        s = history if isinstance(history, pd.Series) else pd.Series(np.asarray(history, float))
        X, y = make_supervised(s, range(1, self.max_horizon + 1), self.lags)
        # chronological holdout for residual spread per horizon (uncertainty estimate)
        n_hold = int(len(X) * self.holdout_frac)
        if n_hold >= self.max_horizon * 2:
            cut = len(s) - int(len(s) * self.holdout_frac)
            X_tr, y_tr = make_supervised(s.iloc[:cut], range(1, self.max_horizon + 1), self.lags)
            m = self._make_model().fit(X_tr, y_tr)
            for h in range(1, self.max_horizon + 1):
                mask = X["h"].values == h
                idx = np.where(mask)[0]
                idx = idx[idx >= int(len(idx) * (1 - self.holdout_frac))] if len(idx) else idx
                if len(idx) > 2:
                    r = y[idx] - m.predict(X.iloc[idx])
                    self.residual_std[h] = float(np.std(r))
        self.model = self._make_model().fit(X, y)
        return self

    def predict(self, history, horizon=24):
        if self.model is None:
            self.fit(history)
        s = history if isinstance(history, pd.Series) else pd.Series(np.asarray(history, float))
        last = make_features(s, self.lags).iloc[[-1]]
        horizon = min(horizon, self.max_horizon)
        rows = pd.concat([last] * horizon, ignore_index=True)
        rows["h"] = np.arange(1, horizon + 1)
        pred = self.model.predict(rows)
        return np.maximum(np.asarray(pred, dtype=float), 1.0)

    def predict_interval(self, history, horizon=24, z=1.28):
        p = self.predict(history, horizon)
        sd = np.array([self.residual_std.get(h, 0.0) for h in range(1, len(p) + 1)])
        return np.maximum(p - z * sd, 1.0), p, p + z * sd


def make_forecaster(name: str, **kw) -> Forecaster:
    name = name.lower()
    if name in ("persistence", "naive"):
        return PersistenceForecaster()
    if name in ("seasonal", "seasonal-naive"):
        return SeasonalNaiveForecaster(**kw)
    if name in ("gbr", "sklearn", "gradient-boosting", "hgb"):
        return GradientBoostingForecaster(backend="sklearn", **kw)
    if name in ("xgb", "xgboost"):
        return GradientBoostingForecaster(backend="xgboost", **kw)
    raise ValueError(f"unknown forecaster {name!r}")
