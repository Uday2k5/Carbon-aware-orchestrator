"""Weather-driven day-ahead carbon-intensity forecaster.

Design (chosen by a walk-forward study on 28 unseen days across five grids):

  1. Target is the *change* from now:  CI(t+h) - CI(t),  h = 1..24.
  2. Inputs: recent history (lags, rolling stats), calendar of origin and target hour, and the
     day-ahead weather forecast for the target hour (wind, sun, temperature, cloud) averaged over
     a few points per grid, plus how much wind / sun / temperature change between now and then.
  3. Model: small gradient-boosted trees (15 leaves, >= 40 samples per leaf, L2 = 1), with the
     physical constraint that more wind can only lower the prediction.
  4. Number of boosting rounds is picked on the most recent 14 days, which the model never
     trained on; then the model is refit on everything with that number of rounds.
  5. Blend layer, fitted on those same 14 held-out days, per horizon band (1-6, 7-12, 13-24 h):
         forecast = now + s * model_change + u * (same_hour_yesterday - now)
     so where the trees are weak the forecast shrinks towards the naive ones on its own.

Diagnostics kept on the object (shown on the dashboard): error on recent training days, on the
held-out days, for both naive baselines, the blend weights, an 80 % error band per horizon and
which inputs matter (permutation importance on the held-out days).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .features import make_features

WX_VARS: Tuple[str, ...] = ("wind", "wind_max", "wind3", "solar", "temp", "cloud")
CHG_VARS: Tuple[str, ...] = ("wind", "solar", "temp")
BUCKETS: Tuple[Tuple[int, int], ...] = ((1, 1), (2, 3), (4, 6), (7, 12), (13, 24))
MARGIN = 0.05                  # a band must beat "same as now" by this much on held-out days to move away from it
VAL_DAYS = 14
MIN_HOURS = 24 * 28            # 14 days to learn from + 14 held out
S_GRID = np.round(np.arange(0.0, 1.21, 0.1), 2)
U_GRID = np.round(np.arange(0.0, 0.81, 0.2), 2)
FRIENDLY = {
    "ci": "carbon intensity now", "wind_tgt": "wind forecast", "wind3_tgt": "wind power forecast",
    "wind_max_tgt": "peak wind forecast", "wind_chg": "change in wind", "solar_tgt": "sunshine forecast",
    "solar_chg": "change in sunshine", "temp_tgt": "temperature forecast", "temp_chg": "change in temperature",
    "cloud_tgt": "cloud forecast", "h": "hours ahead", "th_sin": "hour of day (target)", "th_cos": "hour of day (target)",
    "t_dow": "day of week", "t_wkend": "weekend", "hour": "hour of day (now)", "hour_sin": "hour of day (now)",
    "hour_cos": "hour of day (now)", "dow": "day of week", "roll_mean_24": "last-24 h average",
    "roll_std_24": "last-24 h variability", "roll_mean_168": "last-week average",
}


def _base_features(ci: pd.Series) -> pd.DataFrame:
    f = make_features(ci)
    return f.drop(columns=[c for c in ("month",) if c in f.columns])


def _rows(F: pd.DataFrame, v: np.ndarray, idx: pd.DatetimeIndex, wx: Optional[pd.DataFrame], origins: np.ndarray,
          h: int, with_target: bool) -> pd.DataFrame:
    """Feature rows for the given origin positions at horizon h."""
    x = F.iloc[origins].reset_index(drop=True).copy()
    t_orig = idx[origins]
    t_tgt = t_orig + pd.Timedelta(hours=h)
    x["h"] = h
    x["th_sin"] = np.sin(2 * np.pi * t_tgt.hour / 24)
    x["th_cos"] = np.cos(2 * np.pi * t_tgt.hour / 24)
    x["t_dow"] = t_tgt.dayofweek
    x["t_wkend"] = (t_tgt.dayofweek >= 5).astype(int)
    wt = wx.reindex(t_tgt) if wx is not None else None
    wn = wx.reindex(t_orig) if wx is not None else None
    for c in WX_VARS:
        x[c + "_tgt"] = wt[c].values if wt is not None and c in wt else np.nan
    for c in CHG_VARS:
        x[c + "_chg"] = (wt[c].values - wn[c].values) if wt is not None and c in wt else np.nan
    x["_pers"] = v[origins]
    k = origins + h - 24
    x["_seas"] = np.where(k >= 0, v[np.clip(k, 0, len(v) - 1)], v[origins])
    x["_t_target"] = t_tgt
    if with_target:
        x["_y"] = v[origins + h] - v[origins]
    return x


class WeatherBlendForecaster:
    name = "weather-trees"

    def __init__(self, max_horizon: int = 24, val_days: int = VAL_DAYS, random_state: int = 0, buckets=None, margin: float = MARGIN):
        self.buckets = tuple(buckets or BUCKETS)
        self.margin = margin
        self.max_horizon = max_horizon
        self.val_days = val_days
        self.random_state = random_state
        self.model = None
        self.cols: List[str] = []
        self.blend: Dict[Tuple[int, int], Tuple[float, float]] = {b: (1.0, 0.0) for b in self.buckets}
        self.band: np.ndarray = np.zeros(max_horizon)
        self.diag: dict = {}

    # ------------------------------------------------------------------ fitting
    def _trees(self, n_iter: int):
        from sklearn.ensemble import HistGradientBoostingRegressor
        mono = [(-1 if c in ("wind_tgt", "wind3_tgt", "wind_max_tgt") else 0) for c in self.cols]
        return HistGradientBoostingRegressor(max_iter=n_iter, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40,
                                             l2_regularization=1.0, monotonic_cst=mono, random_state=self.random_state)

    def fit(self, ci: pd.Series, wx: Optional[pd.DataFrame] = None) -> "WeatherBlendForecaster":
        ci = ci.astype(float)
        if len(ci) < MIN_HOURS:
            raise ValueError(f"need {MIN_HOURS} hourly values, have {len(ci)}")
        F, v, idx, n = _base_features(ci), ci.values, ci.index, len(ci)
        parts = [_rows(F, v, idx, wx, np.arange(168, n - h), h, True) for h in range(1, self.max_horizon + 1)]
        df = pd.concat(parts, ignore_index=True)
        self.cols = [c for c in df.columns if not c.startswith("_") and df[c].notna().any()]   # e.g. no weather table: drop empty inputs
        cut = df["_t_target"].max() - pd.Timedelta(days=self.val_days)
        a, b = df[df["_t_target"] <= cut], df[df["_t_target"] > cut]

        probe = self._trees(500).fit(a[self.cols], a["_y"])
        yb, pers_d, seas_d = b["_y"].values, np.zeros(len(b)), (b["_seas"] - b["_pers"]).values
        staged = list(probe.staged_predict(b[self.cols]))
        errs = [float(np.abs(p - yb).mean()) for p in staged]
        best = int(np.argmin(errs)) + 1
        n_iter = int(max(40, min(500, round(best * 1.15))))
        d = staged[min(n_iter, len(staged)) - 1]

        blended = np.zeros(len(b))
        hb = b["h"].values
        for lo, hi in self.buckets:
            mk = (hb >= lo) & (hb <= hi)
            err = lambda su: float(np.abs(yb[mk] - su[0] * d[mk] - su[1] * seas_d[mk]).mean())
            s, u = min(((s, u) for s in S_GRID for u in U_GRID), key=err)
            if err((s, u)) > (1.0 - self.margin) * err((0.0, 0.0)):
                s, u = 0.0, 0.0              # not clearly better than "same as now" on held-out days: do not pretend
            self.blend[(lo, hi)] = (float(s), float(u))
            blended[mk] = s * d[mk] + u * seas_d[mk]
        abs_err = np.abs(yb - blended)
        band = np.array([np.quantile(abs_err[hb == h], 0.8) if (hb == h).any() else np.nan for h in range(1, self.max_horizon + 1)])
        band = pd.Series(band).interpolate(limit_direction="both").rolling(3, center=True, min_periods=1).mean().values
        self.band = band

        self.model = self._trees(n_iter).fit(df[self.cols], df["_y"])
        recent = df[df["_t_target"] > cut]
        self.diag = {
            "rows": int(len(df)), "hours": int(n), "rounds": n_iter, "features": len(self.cols),
            "has_weather": bool(wx is not None and df["wind_tgt"].notna().mean() > 0.5),
            "train_mae": round(float(np.abs(self.model.predict(recent[self.cols]) - recent["_y"].values).mean()), 1),
            "val_mae_trees": round(float(np.abs(yb - d).mean()), 1),
            "val_mae": round(float(abs_err.mean()), 1),
            "val_mae_persistence": round(float(np.abs(yb - pers_d).mean()), 1),
            "val_mae_seasonal": round(float(np.abs(yb - seas_d).mean()), 1),
            "blend": {f"{lo}-{hi}": {"trees": self.blend[(lo, hi)][0], "yesterday": self.blend[(lo, hi)][1]} for lo, hi in self.buckets},
            "drivers": self._drivers(probe, b, yb),
            "trained_through": idx[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        return self

    def _drivers(self, model, b: pd.DataFrame, yb: np.ndarray, top: int = 6) -> List[dict]:
        """Which inputs matter: rise in held-out error when one input is shuffled (grouped by meaning)."""
        rng = np.random.default_rng(self.random_state)
        sub = b.iloc[rng.choice(len(b), size=min(4000, len(b)), replace=False)]
        X, y = sub[self.cols], sub["_y"].values
        base = float(np.abs(model.predict(X) - y).mean())
        groups: Dict[str, List[str]] = {}
        for c in self.cols:
            groups.setdefault(FRIENDLY.get(c, "recent history" if c.startswith("lag_") else c), []).append(c)
        out = []
        for label, cs in groups.items():
            Xp = X.copy()
            perm = rng.permutation(len(Xp))
            for c in cs:
                Xp[c] = Xp[c].values[perm]
            out.append({"name": label, "importance": round(float(np.abs(model.predict(Xp) - y).mean()) - base, 2)})
        out = [o for o in sorted(out, key=lambda o: -o["importance"]) if o["importance"] > 0][:top]
        return out

    # --------------------------------------------------------------- predicting
    def _predict_rows(self, ci: pd.Series, wx: Optional[pd.DataFrame], horizon: int) -> pd.DataFrame:
        ci = ci.astype(float)
        F, v, idx = _base_features(ci), ci.values, ci.index
        last = np.array([len(ci) - 1])
        return pd.concat([_rows(F, v, idx, wx, last, h, False) for h in range(1, horizon + 1)], ignore_index=True)

    def predict_parts(self, ci: pd.Series, wx: Optional[pd.DataFrame] = None, horizon: int = 24) -> dict:
        horizon = min(horizon, self.max_horizon)
        rows = self._predict_rows(ci, wx, horizon)
        d = self.model.predict(rows[self.cols])
        flat = rows.copy()                       # counterfactual: the weather stays as it is now
        if wx is not None:
            now_wx = wx.reindex([ci.index[-1]])
            for c in WX_VARS:
                flat[c + "_tgt"] = float(now_wx[c].iloc[0]) if c in now_wx and pd.notna(now_wx[c].iloc[0]) else np.nan
            for c in CHG_VARS:
                flat[c + "_chg"] = 0.0
        d_flat = self.model.predict(flat[self.cols])
        pers, seas = rows["_pers"].values, rows["_seas"].values
        p, eff = np.zeros(horizon), np.zeros(horizon)
        hh = rows["h"].values
        for (lo, hi), (s, u) in self.blend.items():
            mk = (hh >= lo) & (hh <= hi)
            p[mk] = pers[mk] + s * d[mk] + u * (seas[mk] - pers[mk])
            eff[mk] = s * (d[mk] - d_flat[mk])
        p = np.maximum(p, 0.0)
        band = self.band[:horizon]
        return {"p50": p, "lo": np.maximum(p - band, 0.0), "hi": p + band, "weather_effect": eff,
                "persistence": pers, "seasonal": seas}

    def predict(self, ci: pd.Series, wx: Optional[pd.DataFrame] = None, horizon: int = 24) -> np.ndarray:
        return self.predict_parts(ci, wx, horizon)["p50"]
