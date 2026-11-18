"""Weather forecasts for the carbon forecaster, from Open-Meteo (free, no key).

For every hour we keep the forecast *as it was issued a day earlier* (previous-runs API), so the
model trains on the same quality of information it will have when it forecasts tomorrow.  Hours
still in the future use the latest model run.  Several points per grid are averaged.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd
import requests

from .sources import _get

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
RAW = ("wind_speed_100m", "shortwave_radiation", "temperature_2m", "cloud_cover")
WX_VARS = ("wind", "wind_max", "wind3", "solar", "temp", "cloud")
STORE_VARS = WX_VARS + ("wind_obs",)      # wind_obs: latest model run / analysis, i.e. the wind that actually blew


def fetch_weather(points: Sequence[Sequence[float]], now: datetime, past_days: int, session: requests.Session) -> pd.DataFrame:
    params = {"latitude": ",".join(str(p[0]) for p in points), "longitude": ",".join(str(p[1]) for p in points),
              "hourly": ",".join([v + "_previous_day1" for v in RAW] + list(RAW)), "past_days": int(min(92, max(1, past_days))),
              "forecast_days": 3, "timezone": "UTC", "wind_speed_unit": "ms"}
    res = _get(session, URL, params=params, timeout=90).json()
    res = res if isinstance(res, list) else [res]
    idx = pd.to_datetime(res[0]["hourly"]["time"], utc=True)
    past = np.asarray(idx <= pd.Timestamp(now))

    def mat(key):
        return np.array([[np.nan if x is None else x for x in p["hourly"][key]] for p in res], dtype=float)

    best, latest_wind = {}, None
    for v in RAW:
        issued, latest = mat(v + "_previous_day1"), mat(v)
        if v == "wind_speed_100m":
            latest_wind = latest
        best[v] = np.where(past[None, :], np.where(np.isnan(issued), latest, issued), np.where(np.isnan(latest), issued, latest))
    with np.errstate(all="ignore"):
        w = best["wind_speed_100m"]
        out = pd.DataFrame({
            "wind": np.nanmean(w, axis=0), "wind_max": np.nanmax(w, axis=0), "wind3": np.nanmean(np.minimum(w, 13.0) ** 3, axis=0),
            "solar": np.nanmean(best["shortwave_radiation"], axis=0), "temp": np.nanmean(best["temperature_2m"], axis=0),
            "cloud": np.nanmean(best["cloud_cover"], axis=0),
            "wind_obs": np.where(past, np.nanmean(latest_wind, axis=0), np.nan)}, index=idx)
    return out


def update_weather(store, locations: List[dict], now, session, fetcher=fetch_weather, log=print) -> Dict[str, pd.DataFrame]:
    """Refresh the stored weather table (file weather_hourly.csv, columns '<location>|<variable>')."""
    p = store.dir / "weather_hourly.csv"
    if p.exists():
        wide = pd.read_csv(p)
        wide["timestamp"] = pd.to_datetime(wide["timestamp"], utc=True)
        wide = wide.set_index("timestamp").sort_index()
    else:
        wide = pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
    for loc in locations:
        pts = loc.get("weather_points")
        if not pts:
            continue
        lid = loc["id"]
        have = wide[f"{lid}|wind"].dropna() if f"{lid}|wind" in wide.columns else pd.Series(dtype=float)
        obs = wide[f"{lid}|wind_obs"].dropna() if f"{lid}|wind_obs" in wide.columns else pd.Series(dtype=float)
        past_days = 4 if (len(have) > 24 * 60 and len(obs) > 24 * 10) else 92
        try:
            wx = fetcher(pts, pd.Timestamp(now).to_pydatetime(), past_days, session)
        except Exception as exc:
            log(f"  ! weather {lid}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        wide = wide.reindex(wide.index.union(wx.index))
        for c in STORE_VARS:
            if c not in wx.columns:
                continue
            col = f"{lid}|{c}"
            if col not in wide.columns:
                wide[col] = np.nan
            vals = wx[c].values
            if c == "wind_obs":            # never overwrite a stored observation with a blank
                vals = np.where(np.isnan(vals), wide.loc[wx.index, col].values, vals)
            wide.loc[wx.index, col] = vals
    if len(wide):
        wide = wide[wide.index >= wide.index.max() - pd.Timedelta(days=200)].sort_index()
        out = wide.round(2).copy()
        out.index = out.index.strftime("%Y-%m-%dT%H:%M:%SZ")
        out.index.name = "timestamp"
        out.to_csv(p)
    result = {}
    for loc in locations:
        lid = loc["id"]
        cols = [f"{lid}|{c}" for c in STORE_VARS if f"{lid}|{c}" in wide.columns]
        if cols:
            df = wide[cols].copy()
            df.columns = [c.split("|", 1)[1] for c in cols]
            if df["wind"].notna().any():
                result[lid] = df
    return result
