"""Forecast providers used by simulated policies.

Oracle = perfect future knowledge (upper bound). Noisy = oracle + multiplicative error
growing with horizon (cheap stand-in for a real model). Model = a cao.forecast Forecaster
refit on the history seen so far.
"""
from __future__ import annotations

import zlib
from typing import Dict, Iterable, Optional

import numpy as np


class ForecastProvider:
    name = "base"

    def forecast(self, region: str, t: int, horizon: int) -> np.ndarray:
        raise NotImplementedError

    def all(self, regions: Iterable[str], t: int, horizon: int) -> Dict[str, np.ndarray]:
        return {r: self.forecast(r, t, horizon) for r in regions}


class OracleForecast(ForecastProvider):
    name = "oracle"

    def __init__(self, traces: Dict[str, Iterable[float]]):
        self.traces = {r: np.asarray(list(v), dtype=float) for r, v in traces.items()}

    def forecast(self, region: str, t: int, horizon: int) -> np.ndarray:
        arr = self.traces[region]
        seg = arr[t:t + horizon]
        if len(seg) < horizon:
            pad_val = arr[-1] if len(arr) else 0.0
            seg = np.concatenate([seg, np.full(horizon - len(seg), pad_val)])
        return seg.astype(float)


class NoisyForecast(OracleForecast):
    """Truth x (1 + N(0, sigma_rel * (1 + growth * h))). Slot 0 (now) is exact."""

    def __init__(self, traces, sigma_rel: float = 0.10, seed: int = 0, growth_per_slot: float = 0.02):
        super().__init__(traces)
        self.sigma_rel = sigma_rel
        self.seed = seed
        self.growth = growth_per_slot
        self.name = f"noisy(sigma={sigma_rel:.2f})"

    def forecast(self, region: str, t: int, horizon: int) -> np.ndarray:
        truth = super().forecast(region, t, horizon)
        key = zlib.crc32(f"{self.seed}|{region}|{t}".encode()) & 0xFFFFFFFF
        rng = np.random.default_rng(key)
        h = np.arange(horizon)
        sigma = self.sigma_rel * (1.0 + self.growth * h)
        noise = rng.normal(0.0, 1.0, size=horizon) * sigma
        noise[0] = 0.0
        return np.maximum(truth * (1.0 + noise), 1.0)


class PersistenceForecast(OracleForecast):
    name = "persistence"

    def forecast(self, region: str, t: int, horizon: int) -> np.ndarray:
        arr = self.traces[region]
        now = arr[min(t, len(arr) - 1)]
        return np.full(horizon, float(now))


class SeasonalNaiveForecast(OracleForecast):
    """CI(t+h) = CI at the same hour on the most recent day already observed."""

    def __init__(self, traces, period: int = 24):
        super().__init__(traces)
        self.period = period
        self.name = f"seasonal-naive({period})"

    def forecast(self, region: str, t: int, horizon: int) -> np.ndarray:
        arr = self.traces[region]
        out = np.empty(horizon)
        for h in range(horizon):
            k = t + h
            while k > t:
                k -= self.period
            if k < 0:
                k = t
            out[h] = arr[min(k, len(arr) - 1)]
        return out


class ModelForecast(OracleForecast):
    """Wrap a cao.forecast Forecaster; refit every `refit_every` slots on the observed history."""

    def __init__(self, traces, forecaster_factory, refit_every: int = 24, min_history: int = 24 * 7):
        super().__init__(traces)
        self.factory = forecaster_factory
        self.refit_every = refit_every
        self.min_history = min_history
        self._models: Dict[str, tuple] = {}
        self._cache: Dict[tuple, np.ndarray] = {}
        self.name = "model"

    def forecast(self, region: str, t: int, horizon: int) -> np.ndarray:
        key = (region, t, horizon)
        if key in self._cache:
            return self._cache[key]
        arr = self.traces[region]
        history = arr[: t + 1]
        if len(history) < self.min_history:
            pred = PersistenceForecast({region: arr}).forecast(region, t, horizon)
        else:
            fitted_at, model = self._models.get(region, (-10**9, None))
            if model is None or t - fitted_at >= self.refit_every:
                model = self.factory()
                model.fit(history)
                self._models[region] = (t, model)
            pred = np.asarray(model.predict(history, horizon), dtype=float)
            if len(pred) < horizon:
                pred = np.concatenate([pred, np.full(horizon - len(pred), pred[-1])])
        pred = pred[:horizon].copy()
        pred[0] = arr[min(t, len(arr) - 1)]  # now is observed
        self._cache[key] = pred
        return pred
