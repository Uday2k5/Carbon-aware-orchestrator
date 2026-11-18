"""Forecast log and live track record.

Every forecast the pipeline issues is written down (the value it predicted, its band, when it was
issued, for which hour).  Once the grid has caught up, each logged forecast is scored against what
actually happened.  Rows issued by a real run are marked "live"; rows reconstructed on first start
from models that existed at the time are marked "backfill".

The log also keeps the uncertainty band honest.  The band the model learned in training tends to be
too narrow once the grid drifts, so before a forecast is shown its band is widened by what the last
week of checked forecasts says it needed (a rolling conformal step).  The log always stores the
model's own band, and the widening is recomputed from it using only forecasts that had already been
checked at the time, so the hit rate reported for the widened band is a walk-forward measurement.
"""
from __future__ import annotations

from typing import Dict, Iterable, List

import numpy as np
import pandas as pd

ISO = "%Y-%m-%dT%H:%M:%SZ"
H1 = pd.Timedelta(hours=1)
HORIZONS = (1, 3, 6, 12, 24)
COLS = ["issued", "location", "h", "target", "p50", "lo", "hi", "model", "src"]
FILE = "fc_log.csv"
KEEP_DAYS = 30
COVERAGE = 0.80
RECAL_DAYS = 7           # the band is checked against the last week of forecasts that have come true
RECAL_MIN = 48           # fewer checked forecasts than this: leave the model's band alone
BANDS = {1: (1, 1), 3: (2, 3), 6: (4, 6), 12: (7, 12), 24: (13, 24)}     # logged horizon -> the horizons it speaks for


def _load(store) -> pd.DataFrame:
    df = store.read_rows(FILE)
    return df if len(df) else pd.DataFrame(columns=COLS)


def _rows(issued: pd.Timestamp, loc: str, p: dict, src: str) -> List[list]:
    out = []
    for h in HORIZONS:
        if h > len(p["p50"]):
            continue
        raw_lo, raw_hi = p.get("lo_raw", p.get("lo")), p.get("hi_raw", p.get("hi"))          # always the model's own band
        lo = None if raw_lo is None else round(float(raw_lo[h - 1]), 1)
        hi = None if raw_hi is None else round(float(raw_hi[h - 1]), 1)
        out.append([issued.strftime(ISO), loc, h, (issued + h * H1).strftime(ISO), round(float(p["p50"][h - 1]), 1), lo, hi, p.get("model", ""), src])
    return out


def log_forecasts(store, issued: pd.Timestamp, preds: Dict[str, dict], src: str = "live") -> int:
    """Append the forecasts issued at `issued` (skips locations already logged for that hour)."""
    log = _load(store)
    key = issued.strftime(ISO)
    seen = set(log.loc[log["issued"] == key, "location"]) if len(log) else set()
    rows = [r for loc, p in preds.items() if loc not in seen for r in _rows(issued, loc, p, src)]
    if rows:
        new = pd.concat([log, pd.DataFrame(rows, columns=COLS)], ignore_index=True) if len(log) else pd.DataFrame(rows, columns=COLS)
        cutoff = (issued - pd.Timedelta(days=KEEP_DAYS)).strftime(ISO)
        new[new["issued"] >= cutoff].to_csv(store.dir / FILE, index=False)
    return len(rows)


def backfill_log(store, hours: Iterable[pd.Timestamp], table: Dict[str, List[dict]]) -> int:
    """Write reconstructed past forecasts (from models that existed then) for hours not logged yet."""
    log = _load(store)
    seen = set(zip(log["issued"], log["location"])) if len(log) else set()
    rows = []
    for loc, parts in table.items():
        for h, p in zip(hours, parts):
            if p is not None and (h.strftime(ISO), loc) not in seen:
                rows += _rows(h, loc, p, "backfill")
    if rows:
        new = pd.concat([log, pd.DataFrame(rows, columns=COLS)], ignore_index=True) if len(log) else pd.DataFrame(rows, columns=COLS)
        new.sort_values(["issued", "location", "h"]).to_csv(store.dir / FILE, index=False)
    return len(rows)


def score_log(store, filled: pd.DataFrame, last_complete: pd.Timestamp) -> pd.DataFrame:
    """Logged forecasts whose target hour has happened, with the actual value and the naive error."""
    log = _load(store)
    if log.empty:
        return log
    log = log.copy()
    log["issued"] = pd.to_datetime(log["issued"], utc=True)
    log["target"] = pd.to_datetime(log["target"], utc=True)
    log = log[log["target"] <= last_complete]
    if log.empty:
        return log
    actual, now_v = [], []
    for loc, g in log.groupby("location", sort=False):
        s = filled[loc] if loc in filled.columns else pd.Series(dtype=float)
        actual.append(pd.Series(s.reindex(g["target"]).values, index=g.index))
        now_v.append(pd.Series(s.reindex(g["issued"]).values, index=g.index))
    log["actual"] = pd.concat(actual)
    log["naive"] = pd.concat(now_v)
    log = log.dropna(subset=["actual", "naive"])
    log["err"] = (log["p50"] - log["actual"]).abs()
    log["naive_err"] = (log["naive"] - log["actual"]).abs()
    log["inside"] = (log["actual"] >= log["lo"]) & (log["actual"] <= log["hi"])
    return recalibrate(log)


def _need(scores: np.ndarray) -> float:
    """How much wider the band had to be for COVERAGE of these checked forecasts to fall inside (never negative)."""
    n = len(scores)
    return max(float(np.quantile(scores, min(1.0, COVERAGE * (1 + 1.0 / n)))), 0.0)


def recalibrate(scored: pd.DataFrame) -> pd.DataFrame:
    """Add the band as it would have been shown: widened using only forecasts already checked when it was issued."""
    out = scored.copy()
    out["widen"], out["calibrated"] = 0.0, False
    week = np.timedelta64(RECAL_DAYS * 24, "h")
    for _, g in out.groupby(["location", "h"], sort=False):
        iss, tgt = g["issued"].values, g["target"].values
        score = np.maximum(g["lo"].values.astype(float) - g["actual"].values, g["actual"].values - g["hi"].values.astype(float))
        ok = ~np.isnan(score)
        widen, cal = np.zeros(len(g)), np.zeros(len(g), dtype=bool)
        for i in range(len(g)):
            m = ok & (tgt <= iss[i]) & (iss >= iss[i] - week)
            if m.sum() >= RECAL_MIN:
                widen[i], cal[i] = _need(score[m]), True
        out.loc[g.index, "widen"], out.loc[g.index, "calibrated"] = widen, cal
    out["lo_adj"] = (out["lo"] - out["widen"]).clip(lower=0.0)
    out["hi_adj"] = out["hi"] + out["widen"]
    out["inside_adj"] = (out["actual"] >= out["lo_adj"]) & (out["actual"] <= out["hi_adj"])
    return out


def band_widening(scored: pd.DataFrame, at: pd.Timestamp) -> Dict[str, Dict[int, float]]:
    """Per location and logged horizon: how much to widen the band of a forecast issued at `at`."""
    out: Dict[str, Dict[int, float]] = {}
    if scored.empty:
        return out
    recent = scored[(scored["target"] <= at) & (scored["issued"] >= at - pd.Timedelta(days=RECAL_DAYS))]
    for (loc, h), g in recent.groupby(["location", "h"]):
        score = np.maximum(g["lo"] - g["actual"], g["actual"] - g["hi"]).dropna().values
        if len(score) >= RECAL_MIN:
            out.setdefault(loc, {})[int(h)] = round(_need(score), 1)
    return out


def apply_widening(preds: Dict[str, dict], widen: Dict[str, Dict[int, float]]) -> None:
    """Widen the bands in place; the model's own band stays available as lo_raw / hi_raw."""
    for loc, p in preds.items():
        w = widen.get(loc)
        if not w or p.get("lo") is None or p.get("hi") is None:
            continue
        add = np.zeros(len(p["p50"]))
        for h, (a, b) in BANDS.items():
            add[a - 1:b] = w.get(h, 0.0)
        p["lo_raw"], p["hi_raw"] = np.asarray(p["lo"], dtype=float), np.asarray(p["hi"], dtype=float)
        p["lo"], p["hi"] = np.maximum(p["lo_raw"] - add, 0.0), p["hi_raw"] + add


def track_summary(scored: pd.DataFrame) -> Dict[str, dict]:
    """Per location: how the forecasts actually issued by live runs have done so far."""
    out: Dict[str, dict] = {}
    if scored.empty:
        return out
    for loc, g in scored.groupby("location"):
        live = g[g["src"] == "live"]
        e = {"logged": int(len(g)), "live_scored": int(len(live))}
        cal = g[g["calibrated"]].dropna(subset=["lo", "hi"])
        if len(cal):                                     # walk-forward check of the live recalibration, all logged forecasts
            e["recal"] = {"n": int(len(cal)), "window_days": RECAL_DAYS, "target_pct": COVERAGE * 100,
                          "model_band_hit_pct": round(float(cal["inside"].mean() * 100), 1), "hit_pct": round(float(cal["inside_adj"].mean() * 100), 1),
                          "model_band_width": round(float((cal["hi"] - cal["lo"]).mean()), 1), "width": round(float((cal["hi_adj"] - cal["lo_adj"]).mean()), 1)}
        if len(live):
            banded = live.dropna(subset=["lo", "hi"])
            e.update({"since": live["issued"].min().strftime(ISO), "mae": round(float(live["err"].mean()), 1),
                      "naive_mae": round(float(live["naive_err"].mean()), 1),
                      "band_hit_pct": round(float(banded["inside_adj"].mean() * 100), 1) if len(banded) else None,
                      "by_h": {str(int(h)): {"mae": round(float(x["err"].mean()), 1), "naive": round(float(x["naive_err"].mean()), 1), "n": int(len(x))}
                               for h, x in live.groupby("h")}})
        out[loc] = e
    return out
