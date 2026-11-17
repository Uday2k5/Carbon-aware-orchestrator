"""`cao live tick`: fetch live grid data -> update hourly store -> forecast -> advance the
scheduling twin for every newly completed hour -> write the dashboard JSON -> copy the web app."""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "2")   # many small boosted fits: more threads only add overhead

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd
import requests

from ..core.config import load_settings
from ..migration.cost_model import MigrationCostModel
from .config import load_dotenv, load_live_config
from .forecasting import daily_backtest, fit_models, predict
from .sources import FORWARD, SOURCES, MissingKey, to_hourly
from .store import LiveStore
from .twin import ISO, LiveTwin

ROOT = Path(__file__).resolve().parents[2]
H1 = pd.Timedelta(hours=1)
STATE_VERSION = 2          # bump when twin logic changes; the hosted twin then rebuilds from recorded data
DEC_COLS = ["ts", "job", "kind", "state_gb", "action", "from", "to", "saved_g", "migration_g", "payback_h",
            "remaining_h", "resume_at", "reason"]


def _iso(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime(ISO)


def _default_cost_model() -> MigrationCostModel:
    p = ROOT / "config" / "migration_model.json"
    if p.exists():
        return MigrationCostModel.from_json(p)
    s = load_settings()
    return MigrationCostModel.from_config(s.migration_model, s.network)


def tick(site_dir="site", config_path=None, now=None, session=None, sources: Optional[Dict[str, Callable]] = None,
         forward: Optional[Dict[str, Callable]] = None, cost_model=None, web_dir=None, log: Callable = print) -> dict:
    t_start = time.perf_counter()
    load_dotenv(ROOT / ".env")
    cfg = load_live_config(config_path)
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    site = Path(site_dir)
    store = LiveStore(site / "data")
    sources = SOURCES if sources is None else sources
    forward = FORWARD if forward is None else forward
    session = session or requests.Session()
    cm = cost_model or _default_cost_model()
    last_complete = now.floor("h") - H1

    # ------------------------------------------------------------ 1. collect
    wide = store.load_ci()
    latest = store.load_json("latest.json", {}) or {}
    status, errors, rows = {}, {}, {}
    for loc in cfg.locations:
        lid = loc["id"]
        try:
            have = wide[lid].dropna() if lid in wide.columns else pd.Series(dtype=float)
            floor0 = now - pd.Timedelta(days=cfg.backfill_days)
            start = max(have.index.max() - 3 * H1, floor0) if len(have) else floor0
            native = sources[loc["source"]](loc, start.to_pydatetime(), now.to_pydatetime(), session)
            hourly = to_hourly(native, now)
            if len(hourly):
                wide = wide.reindex(wide.index.union(hourly.index))
                if lid not in wide.columns:
                    wide[lid] = np.nan
                wide.loc[hourly.index, lid] = hourly.values
            if len(native):
                step = native["timestamp"].diff().median() if len(native) > 2 else pd.Timedelta(0)
                valid_until = min(native["timestamp"].iloc[-1] + (step if pd.notna(step) else pd.Timedelta(0)), now)
                latest[lid] = {"ts": _iso(valid_until), "ci": round(float(native["ci"].iloc[-1]), 1)}
            rows[lid] = int(len(native))
            status[lid] = "live" if len(native) else "no-data"
        except MissingKey:
            status[lid] = "awaiting-key"
        except Exception as exc:  # keep the tick alive; show the location as stale
            status[lid] = "error"
            errors[lid] = f"{type(exc).__name__}: {str(exc)[:160]}"
            log(f"  ! {lid}: {errors[lid]}")
    for lid, info in latest.items():
        if status.get(lid) in ("live", "error") and now - pd.Timestamp(info["ts"]) > 3 * H1:
            status[lid] = "stale"
    if len(wide):
        wide = wide.sort_index()
        wide = wide.reindex(pd.date_range(wide.index.min(), max(wide.index.max(), last_complete), freq="1h", name="timestamp"))
        wide = wide[wide.index <= last_complete]
    store.save_ci(wide)
    store.save_json("latest.json", latest)
    if wide.empty or wide.dropna(how="all").empty:
        raise RuntimeError("no carbon data could be fetched for any location")

    filled = wide.interpolate(limit=3, limit_area="inside")       # short gaps only
    recent = filled.ffill(limit=3)                                # usable as "current" for <= 3 h
    carried = filled.ffill()                                      # accounting for jobs in a stale location

    def enabled_at(h) -> list:
        row = recent.loc[h]
        return [c for c in recent.columns if pd.notna(row[c])]

    # ------------------------------------------------------------ 2. accuracy + model selection (once per UTC day)
    today = (last_complete + H1).strftime("%Y-%m-%d")
    acc = store.load_json("accuracy.json")
    if not acc or acc.get("date") != today:
        per = daily_backtest(filled, last_complete)
        snaps = store.read_rows("official_fc.csv")
        for lid, a_ in per.items():
            day = a_["last_day"]["day"]
            sn = snaps[(snaps["issued"] == day) & (snaps["location"] == lid)] if len(snaps) else snaps
            if len(sn) >= 12:
                tgt = pd.to_datetime(sn["target"], utc=True)
                actual = filled[lid].reindex(tgt).values
                ok = ~np.isnan(actual)
                if ok.sum() >= 12:
                    a_["mae_official_last_day"] = round(float(np.abs(sn["ci"].values[ok] - actual[ok]).mean()), 1)
                    a_["mae_ours_last_day"] = round(float(np.abs(np.array(a_["last_day"]["ours"]) - np.array(a_["last_day"]["actual"])).mean()), 1)
        acc = {"date": today, "per_location": per,
               "method": "walk-forward: every candidate refit on data before each of the last 14 days; each day uses the "
                         "candidate that was best over the previous week; errors shown are for the last 7 days"}
        store.save_json("accuracy.json", acc)
    selection = {k: v["selected"] for k, v in acc["per_location"].items()}
    bands = {k: v.get("band") for k, v in acc["per_location"].items()}

    # ------------------------------------------------------------ 3. twin
    state = store.load_json("state.json")
    if state is not None and state.get("version") != STATE_VERSION:
        state = None
        (store.dir / "decisions.csv").unlink(missing_ok=True)
    if state is None:
        epoch = max(last_complete - (cfg.warm_start_hours - 1) * H1, wide.dropna(how="all").index.min() + 240 * H1)
        epoch = min(epoch, last_complete)
        twin = LiveTwin.new(cfg, cm, epoch)
        pending = pd.date_range(epoch, last_complete, freq="1h")
    else:
        twin = LiveTwin(cfg, cm, state)
        pending = pd.date_range(twin.last_hour + H1, last_complete, freq="1h") if twin.last_hour is not None else pd.DatetimeIndex([])
    feed, preds = [], {}
    models = fit_models(filled, (pending[0] - H1) if len(pending) else last_complete)
    for h in pending:
        en = enabled_at(h)
        if not en:
            twin.last_hour = h
            continue
        preds = predict(models, filled, h, selection if len(pending) <= 6 else None)   # replays use the plain boosted model
        ci_now = {c: float(carried.loc[h, c]) for c in carried.columns if pd.notna(carried.loc[h, c])}
        fc = {c: np.concatenate([[ci_now[c]], preds[c]["p50"][:23]]) if c in preds else np.full(24, ci_now[c]) for c in ci_now}
        feed.extend(twin.advance(h, ci_now, fc, en))
    if len(pending) > 6:                                          # after a replay, refresh the display model
        models = fit_models(filled, last_complete)
    preds = predict(models, filled, last_complete, selection, bands)
    store.save_json("state.json", dict(twin.to_state(), version=STATE_VERSION))
    store.append_rows("decisions.csv", [[r[c] for c in DEC_COLS] for r in feed], DEC_COLS)

    # ------------------------------------------------------------ 4. official forward forecasts (where published)
    official = {}
    for loc in cfg.locations:
        fn = forward.get(loc["source"])
        if fn is None or status.get(loc["id"]) != "live":
            continue
        try:
            nat = fn(loc, now.to_pydatetime(), session)
            s = nat.set_index("timestamp")["ci"].astype(float)
            official[loc["id"]] = s.groupby(s.index.floor("h")).mean()
        except Exception as exc:
            log(f"  ! official forecast {loc['id']}: {str(exc)[:120]}")
    snaps = store.read_rows("official_fc.csv")
    new_rows = []
    for lid, s in official.items():
        if len(snaps) and ((snaps["issued"] == today) & (snaps["location"] == lid)).any():
            continue
        new_rows += [[today, lid, _iso(t), round(float(v), 1)] for t, v in s.items()]
    store.append_rows("official_fc.csv", new_rows, ["issued", "location", "target", "ci"], keep_last=6000)

    # ------------------------------------------------------------ 5. dashboard json
    locations = []
    for loc in cfg.locations:
        lid = loc["id"]
        entry = {k: loc.get(k) for k in ("id", "name", "country", "operator", "url")}
        entry["status"] = status.get(lid, "error")
        if lid in errors:
            entry["error"] = errors[lid]
        if lid in filled.columns and filled[lid].notna().any():
            h72 = filled[lid].dropna().tail(72)
            w7 = filled[lid].dropna().tail(168)
            entry["history"] = [[_iso(t), round(float(v), 1)] for t, v in h72.items()]
            entry["stats7d"] = {"min": round(float(w7.min()), 1), "mean": round(float(w7.mean()), 1), "max": round(float(w7.max()), 1)}
            entry["hours_of_history"] = int(filled[lid].notna().sum())
        if lid in latest:
            entry["ci_now"] = latest[lid]["ci"]
            entry["updated_at"] = latest[lid]["ts"]
        if lid in preds:
            p = preds[lid]
            hrs = pd.date_range(last_complete + H1, periods=len(p["p50"]), freq="1h")
            entry["forecast_model"] = p["model"]
            entry["forecast"] = [[_iso(t), None if p["lo"] is None else round(float(p["lo"][i]), 1), round(float(p["p50"][i]), 1),
                                  None if p["hi"] is None else round(float(p["hi"][i]), 1)] for i, t in enumerate(hrs)]
        if lid in official:
            entry["official_forecast"] = [[_iso(t), round(float(v), 1)] for t, v in official[lid].items()]
        locations.append(entry)

    tw = twin.summary()
    tw["decisions"] = store.read_rows("decisions.csv").tail(80).iloc[::-1].replace({np.nan: None}).to_dict(orient="records")
    meta = store.load_json("meta.json", {}) or {}
    meta["ticks"] = int(meta.get("ticks", 0)) + 1
    meta.setdefault("first_tick", _iso(now))
    store.save_json("meta.json", meta)
    live = {
        "meta": {"generated_at": _iso(now), "last_complete_hour": _iso(last_complete), "ticks": meta["ticks"],
                 "first_tick": meta["first_tick"], "title": cfg.site.get("title"), "repo_url": cfg.site.get("repo_url"),
                 "build_seconds": None,
                 "notes": {"workloads": "simulated", "grid_data": "live from the operators listed per location",
                           "cost_model": cm.source, "replayed_hours": cfg.warm_start_hours}},
        "locations": locations,
        "latency_ms": cfg.latency_ms,
        "accuracy": acc,
        "twin": tw,
        "cost_model": {"checkpoint": [cm.checkpoint.a, cm.checkpoint.b], "transfer": [cm.transfer.a, cm.transfer.b],
                       "restore": [cm.restore.a, cm.restore.b], "network_kwh_per_gb": cm.network_kwh_per_gb,
                       "network_ci": cm.network_ci_attribution, "source": cm.source},
    }
    live["meta"]["build_seconds"] = round(time.perf_counter() - t_start, 1)
    store.save_json("live.json", live)

    # ------------------------------------------------------------ 6. web app
    web = Path(web_dir) if web_dir else ROOT / "web"
    if web.exists():
        shutil.copytree(web, site, dirs_exist_ok=True)
    (site / ".nojekyll").write_text("")
    return {"now": _iso(now), "status": status, "errors": errors, "rows": rows, "hours_processed": len(pending), "new_decisions": len(feed),
            "totals": {p["id"]: p["total_g"] for p in tw["policies"]}, "site": str(site), "seconds": live["meta"]["build_seconds"]}
