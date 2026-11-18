"""Grid anomaly detector, built on the forecaster.

An hour is unusual when the grid landed far from where the model, three hours earlier, expected it:
outside the forecast band AND beyond that grid's own alarm line.  The gap is measured in units of
the grid's usual forecast error (median absolute deviation over the trailing two weeks).  The alarm
line is THRESHOLD of those units, or higher on grids whose errors have heavy tails: it is raised to
the level only about one hour in a hundred crosses, so a volatile grid is not flagged for being itself.
Consecutive unusual hours are merged into one event, and each event gets a first explanation by
comparing the wind that actually blew with the wind that had been forecast.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

ISO = "%Y-%m-%dT%H:%M:%SZ"
H1 = pd.Timedelta(hours=1)
THRESHOLD = 3.0
RARE = 0.99             # the alarm line is never below the level this share of a grid's own hours stays under
LEAD_H = 3
SCALE_DAYS = 14
EVENT_DAYS = 7
WIND_GAP = 1.5          # m/s difference between observed and forecast wind that counts as an explanation


def detect(scored: pd.DataFrame, weather: Dict[str, pd.DataFrame], last_complete: pd.Timestamp) -> dict:
    out = {"threshold": THRESHOLD, "rare_pct": round((1 - RARE) * 100, 1), "lead_h": LEAD_H, "events": [], "latest": {}, "per_location": {},
           "hours_checked": 0, "alarm_rate_pct": None}
    if scored is None or scored.empty:
        return out
    d = scored[(scored["h"] == LEAD_H) & (scored["target"] > last_complete - pd.Timedelta(days=SCALE_DAYS))].copy()
    if d.empty:
        return out
    flagged_total = checked_total = 0
    for loc, g in d.groupby("location"):
        g = g.sort_values("target").drop_duplicates("target", keep="last")
        r = (g["actual"] - g["p50"]).values
        if len(r) < 48:
            continue
        med = float(np.median(r))
        scale = max(1.4826 * float(np.median(np.abs(r - med))), 3.0, 0.03 * float(g["actual"].mean()))
        g = g.assign(z=(r - med) / scale)
        limit = max(THRESHOLD, float(np.quantile(np.abs(g["z"].values), RARE)))
        lo, hi = (g["lo_adj"], g["hi_adj"]) if "lo_adj" in g.columns else (g["lo"], g["hi"])      # the band as it was shown
        outside = (g["actual"] < lo) | (g["actual"] > hi) | lo.isna()
        g = g.assign(flag=(g["z"].abs() >= limit) & outside, lo_shown=lo, hi_shown=hi)
        flagged_total += int(g["flag"].sum())
        checked_total += int(len(g))
        out["per_location"][loc] = {"hours_checked": int(len(g)), "flagged": int(g["flag"].sum()), "scale_g": round(scale, 1), "limit": round(limit, 1)}
        last = g.iloc[-1]
        out["latest"][loc] = {"ts": last["target"].strftime(ISO), "z": round(float(last["z"]), 1), "limit": round(limit, 1), "unusual": bool(last["flag"]),
                              "expected": round(float(last["p50"]), 1), "actual": round(float(last["actual"]), 1)}
        recent = g[(g["target"] > last_complete - pd.Timedelta(days=EVENT_DAYS)) & g["flag"]]
        if recent.empty:
            continue
        run_id = (recent["target"].diff() > 2 * H1).cumsum()
        wx = weather.get(loc)
        for _, ev in recent.groupby(run_id):
            peak = ev.loc[ev["z"].abs().idxmax()]
            dirtier = bool(peak["z"] > 0)
            out["events"].append({
                "location": loc, "start": ev["target"].min().strftime(ISO), "end": ev["target"].max().strftime(ISO),
                "hours": int(len(ev)), "peak": peak["target"].strftime(ISO), "z": round(float(peak["z"]), 1),
                "expected": round(float(peak["p50"]), 1), "actual": round(float(peak["actual"]), 1),
                "band": [None if pd.isna(peak["lo_shown"]) else round(float(peak["lo_shown"]), 1), None if pd.isna(peak["hi_shown"]) else round(float(peak["hi_shown"]), 1)],
                "limit": round(limit, 1),
                "direction": "dirtier" if dirtier else "cleaner", "why": _explain(wx, peak["target"], dirtier),
                "ongoing": bool(ev["target"].max() >= last_complete - H1),
            })
    out["events"].sort(key=lambda e: e["peak"], reverse=True)
    out["hours_checked"] = checked_total
    out["alarm_rate_pct"] = round(flagged_total / checked_total * 100, 2) if checked_total else None
    return out


def _explain(wx: Optional[pd.DataFrame], ts: pd.Timestamp, dirtier: bool) -> dict:
    """Compare the wind that blew with the wind that had been forecast a day ahead."""
    if wx is None or "wind_obs" not in wx.columns or ts not in wx.index:
        return {"kind": "unknown", "text": "no wind observation for that hour yet"}
    fc, obs = wx.loc[ts, "wind"], wx.loc[ts, "wind_obs"]
    if pd.isna(fc) or pd.isna(obs):
        return {"kind": "unknown", "text": "no wind observation for that hour yet"}
    gap = float(obs - fc)
    base = {"wind_forecast": round(float(fc), 1), "wind_observed": round(float(obs), 1)}
    nums = f"{obs:.1f} m/s against {fc:.1f} forecast"
    if dirtier and gap <= -WIND_GAP:
        return dict(base, kind="wind", text=f"less wind than forecast ({nums}), so less clean power than the model counted on")
    if not dirtier and gap >= WIND_GAP:
        return dict(base, kind="wind", text=f"more wind than forecast ({nums}), so more clean power than the model counted on")
    rest = "plant outages, fewer clean imports or higher demand" if dirtier else "more solar, more clean imports or lower demand"
    if abs(gap) < WIND_GAP:
        return dict(base, kind="other", text=f"wind was close to its forecast ({nums}), so this points to {rest}")
    return dict(base, kind="other", text=f"wind missed its forecast the other way ({nums}), so wind does not explain it; this points to {rest}")
