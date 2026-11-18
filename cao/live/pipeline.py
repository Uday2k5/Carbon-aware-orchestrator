"""`cao live tick`: fetch live grid data and weather forecasts -> update the hourly store -> train
and score the forecaster -> advance the scheduling twin for every newly completed hour -> write
the dashboard JSON -> copy the web app."""
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
from .anomaly import detect
from .forecasting import daily_backtest, fit_models, forecast_value_study, hourly_block_forecasts, predict
from .sources import FORWARD, SOURCES, MissingKey, to_hourly
from .store import LiveStore
from .track import apply_widening, backfill_log, band_widening, log_forecasts, score_log, track_summary
from .twin import ISO, LiveTwin
from .weather import fetch_weather, update_weather

ROOT = Path(__file__).resolve().parents[2]
H1 = pd.Timedelta(hours=1)
ACC_VERSION = 2            # bump when the daily scoring changes
STATE_VERSION = 4          # bump when twin logic changes; the hosted twin then rebuilds from recorded data
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
         forward: Optional[Dict[str, Callable]] = None, cost_model=None, web_dir=None, weather_fetcher: Optional[Callable] = None,
         log: Callable = print) -> dict:
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
    bt_days = int(cfg.raw.get("backtest_days", 14))
    bt_refit = int(cfg.raw.get("backtest_refit_days", 2))

    # ------------------------------------------------------------ 1. collect grid data
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
                if native.attrs.get("quality"):
                    latest[lid]["quality"] = native.attrs["quality"]
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
    # Grids whose values the provider estimated rather than measured: shown and scheduled on, clearly labelled,
    # but kept out of everything that trains or scores a model.
    estimated = sorted(lid for lid, info in latest.items() if (info.get("quality") or {}).get("estimated_pct", 0) >= 50 and lid in filled.columns)
    measured = filled.drop(columns=estimated)

    def fit(upto):
        out = fit_models(measured, weather, upto)
        out.update({lid: None for lid in estimated})              # no model on estimated data: naive forecast only
        return out
    recent = filled.ffill(limit=3)                                # usable as "current" for <= 3 h
    carried = filled.ffill()                                      # accounting for jobs in a stale location

    def enabled_at(h) -> list:
        row = recent.loc[h]
        return [c for c in recent.columns if pd.notna(row[c])]

    # ------------------------------------------------------------ 2. weather forecasts (model inputs)
    have_ci = [l for l in cfg.locations if l["id"] in filled.columns and filled[l["id"]].notna().any()]
    weather = update_weather(store, have_ci, now, session, fetcher=weather_fetcher or fetch_weather, log=log)

    # ------------------------------------------------------------ 3. score the forecaster (once per UTC day)
    today = (last_complete + H1).strftime("%Y-%m-%d")
    acc = store.load_json("accuracy.json")
    if not acc or acc.get("date") != today or acc.get("version") != ACC_VERSION:
        per, blocks = daily_backtest(measured, weather, last_complete, bt_days, bt_refit, keep_models=True)
        snaps = store.read_rows("official_fc.csv")
        for lid, a_ in per.items():
            day = (a_.get("last_day") or {}).get("day")
            sn = snaps[(snaps["issued"] == day) & (snaps["location"] == lid)] if (len(snaps) and day) else snaps
            if len(sn) >= 12:
                tgt = pd.to_datetime(sn["target"], utc=True)
                actual = filled[lid].reindex(tgt).values
                ok = ~np.isnan(actual)
                if ok.sum() >= 12:
                    a_["mae_official_last_day"] = round(float(np.abs(sn["ci"].values[ok] - actual[ok]).mean()), 1)
                    a_["mae_ours_last_day"] = round(float(np.abs(np.array(a_["last_day"]["ours"]) - np.array(a_["last_day"]["actual"])).mean()), 1)
        value = None
        try:
            day0 = (last_complete + H1).floor("D")
            span = pd.date_range(day0 - pd.Timedelta(days=bt_days), last_complete, freq="1h")
            table = hourly_block_forecasts(measured, weather, blocks, span)     # what each past hour's model would have issued
            past = span < last_complete                                         # the current hour is logged below as a live forecast
            backfill_log(store, span[past], {c: [x for x, k in zip(t, past) if k] for c, t in table.items()})
            study_hours = span[span < day0]
            value = forecast_value_study(cfg, cm, measured, study_hours, {c: t[:len(study_hours)] for c, t in table.items()})
        except Exception as exc:
            log(f"  ! forecast value study: {type(exc).__name__}: {str(exc)[:140]}")
        acc = {"date": today, "version": ACC_VERSION, "per_location": per, "forecast_value": value,
               "method": f"walk-forward: the model is refit every {bt_refit} days on data before each block of the last {bt_days} days and "
                         "asked for a 24 h forecast four times a day; nothing it is scored on was seen in training"}
        store.save_json("accuracy.json", acc)

    # ------------------------------------------------------------ 4. twin
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
    models = fit((pending[0] - H1) if len(pending) else last_complete)                           # trained before the hours it serves
    for h in pending:
        en = enabled_at(h)
        if not en:
            twin.last_hour = h
            continue
        preds = predict(models, filled, weather, h, explain=False)
        ci_now = {c: float(carried.loc[h, c]) for c in carried.columns if pd.notna(carried.loc[h, c])}
        fc = {c: np.concatenate([[ci_now[c]], preds[c]["p50"][:23]]) if c in preds else np.full(24, ci_now[c]) for c in ci_now}
        naive = {c: np.full(24, ci_now[c]) for c in ci_now}
        feed.extend(twin.advance(h, ci_now, fc, en, naive))
    if len(pending) > 6:                                          # after a replay, refresh the serving model
        models = fit(last_complete)
    preds = predict(models, filled, weather, last_complete)
    store.save_json("state.json", dict(twin.to_state(), version=STATE_VERSION))

    # ------------------------------------------------------------ 4b. log what was just forecast, score what has matured, look for anomalies
    log_forecasts(store, last_complete, preds, "live")
    scored = score_log(store, filled, last_complete)
    widen = band_widening(scored, last_complete)                  # what the last week of checked forecasts says the band needs
    apply_widening(preds, widen)
    track = track_summary(scored)
    for lid, w in widen.items():
        track.setdefault(lid, {})["widen_now"] = {str(h): v for h, v in sorted(w.items())}
    anomalies = detect(scored[~scored["location"].isin(estimated)] if len(scored) else scored, weather, last_complete)
    store.append_rows("decisions.csv", [[r[c] for c in DEC_COLS] for r in feed], DEC_COLS)

    # ------------------------------------------------------------ 5. operators' own forward forecasts (where published)
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

    # ------------------------------------------------------------ 6. dashboard json
    fhours = pd.date_range(last_complete + H1, periods=24, freq="1h")
    r1 = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 1)
    locations, model_cards = [], {}
    for loc in cfg.locations:
        lid = loc["id"]
        entry = {k: loc.get(k) for k in ("id", "name", "country", "operator", "url")}
        entry["status"] = status.get(lid, "error")
        if lid in estimated:
            entry["estimated"] = latest[lid]["quality"]
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
            entry["forecast_model"] = p["model"]
            entry["forecast"] = [[_iso(t), None if p["lo"] is None else r1(p["lo"][i]), r1(p["p50"][i]),
                                  None if p["hi"] is None else r1(p["hi"][i])] for i, t in enumerate(fhours[:len(p["p50"])])]
            if p.get("weather_effect") is not None:
                entry["weather_effect"] = [r1(v) for v in p["weather_effect"]]
        if lid in weather:
            wx = weather[lid].reindex(pd.date_range(last_complete - 23 * H1, periods=48, freq="1h"))
            entry["weather"] = [[_iso(t), r1(row["wind"]), r1(row["solar"]), r1(row["temp"])] for t, row in wx.iterrows()]
        if lid in official:
            entry["official_forecast"] = [[_iso(t), round(float(v), 1)] for t, v in official[lid].items()]
        m = models.get(lid)
        if m is not None:
            model_cards[lid] = m.diag
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
                 "build_seconds": None, "estimated_grids": estimated,
                 "notes": {"workloads": "simulated", "grid_data": "live from the operators listed per location",
                           "cost_model": cm.source, "replayed_hours": cfg.warm_start_hours}},
        "locations": locations,
        "latency_ms": cfg.latency_ms,
        "accuracy": acc,
        "track": track,
        "anomalies": anomalies,
        "models": {"forecaster": {
            "name": "Weather-driven carbon forecaster",
            "predicts": "grid carbon intensity for each of the next 24 hours, per grid",
            "algorithm": "gradient-boosted trees on the change from now (15 leaves, at least 40 samples per leaf, more wind can only lower it), "
                         "then a blend with 'same as now' and 'same hour yesterday' learned per horizon band",
            "inputs": "day-ahead weather forecasts (wind, sunshine, temperature, cloud; several points per grid), recent history, calendar",
            "weather_source": "Open-Meteo, forecasts as issued one day earlier",
            "retrained": _iso(now), "validation": "boosting rounds and blend weights are chosen on the most recent 14 days, never on training data",
            "uncertainty": "two more tree models predict the 10th and 90th percentile; the band is calibrated on the held-out days, "
                           "then widened live by what the last week of checked forecasts says it needed",
            "per_location": model_cards}},
        "twin": tw,
        "cost_model": {"checkpoint": [cm.checkpoint.a, cm.checkpoint.b], "transfer": [cm.transfer.a, cm.transfer.b],
                       "restore": [cm.restore.a, cm.restore.b], "network_kwh_per_gb": cm.network_kwh_per_gb,
                       "network_ci": cm.network_ci_attribution, "source": cm.source},
    }
    live["meta"]["build_seconds"] = round(time.perf_counter() - t_start, 1)
    store.save_json("live.json", live)

    # ------------------------------------------------------------ 7. web app
    web = Path(web_dir) if web_dir else ROOT / "web"
    if web.exists():
        shutil.copytree(web, site, dirs_exist_ok=True)
    (site / ".nojekyll").write_text("")
    return {"now": _iso(now), "status": status, "errors": errors, "rows": rows, "estimated": estimated, "hours_processed": len(pending),
            "new_decisions": len(feed), "totals": {p["id"]: p["total_g"] for p in tw["policies"]}, "site": str(site),
            "seconds": live["meta"]["build_seconds"], "weather": sorted(weather), "accuracy": acc.get("per_location", {}),
            "forecast_value": acc.get("forecast_value"), "anomalies": anomalies, "track": track}
