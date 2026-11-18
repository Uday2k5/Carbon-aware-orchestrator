import json

import numpy as np
import pandas as pd
import pytest
import yaml

from cao.live.config import load_live_config
from cao.live.pipeline import tick
from cao.live.sources import MissingKey, to_hourly

BASE = {"north-west-england": 60, "london": 200, "south-wales": 330, "denmark-west": 110, "france": 40}


def _windiness(ts):
    """Slow deterministic 'weather' signal in 0..1 shared by the fake grid feed and the fake weather feed."""
    hours = (ts - pd.Timestamp("2026-01-01", tz="UTC")) / pd.Timedelta(hours=1)
    return 0.5 + 0.5 * np.sin(2 * np.pi * np.asarray(hours, dtype=float) / 79.0)


def fake_source(loc, start, end, session):
    if loc["id"] not in BASE:
        raise MissingKey("ELECTRICITY_MAPS_TOKEN")
    ts = pd.date_range(pd.Timestamp(start).floor("30min"), pd.Timestamp(end), freq="30min")
    phase = (sum(map(ord, loc["id"])) % 24) / 24 * 2 * np.pi
    wob = 0.15 * np.sin(2 * np.pi * ts.hour / 24 + phase) - 0.45 * _windiness(ts)        # windier -> cleaner
    return pd.DataFrame({"timestamp": ts, "ci": BASE[loc["id"]] * (1.3 + wob)})


def fake_weather(points, now, past_days, session):
    idx = pd.date_range(pd.Timestamp(now).floor("h") - pd.Timedelta(days=past_days), pd.Timestamp(now).floor("h") + pd.Timedelta(days=3), freq="1h")
    wind = 3 + 10 * _windiness(idx)
    return pd.DataFrame({"wind": wind, "wind_max": wind + 1, "wind3": np.minimum(wind, 13) ** 3, "solar": 100.0, "temp": 10.0, "cloud": 50.0}, index=idx)


@pytest.fixture(scope="module")
def small_cfg(tmp_path_factory):
    cfg = load_live_config().raw
    cfg = dict(cfg, backfill_days=40, warm_start_hours=6, backtest_days=4, backtest_refit_days=2)
    p = tmp_path_factory.mktemp("cfg") / "live.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def test_config_latency_is_symmetric():
    cfg = load_live_config()
    assert "india-north" in cfg.ids and len(cfg.ids) == 6
    for a in cfg.ids:
        assert cfg.latency_ms[a][a] == 5
        for b in cfg.ids:
            assert cfg.latency_ms[a][b] == cfg.latency_ms[b][a]


def test_to_hourly_drops_hour_in_progress():
    ts = pd.date_range("2026-11-17T10:00Z", periods=6, freq="30min")
    h = to_hourly(pd.DataFrame({"timestamp": ts, "ci": [10, 20, 30, 40, 50, 60]}), pd.Timestamp("2026-11-17T12:10Z"))
    assert list(h.index.hour) == [10, 11] and list(h.values) == [15.0, 35.0]


def test_tick_end_to_end_and_resume(small_cfg, tmp_path):
    site = tmp_path / "site"
    kw = dict(config_path=small_cfg, sources={k: fake_source for k in ("gb-regional", "energidata", "rte-eco2mix", "electricity-maps")},
              forward={}, web_dir=tmp_path / "noweb", weather_fetcher=fake_weather, log=lambda *_: None)
    out = tick(site, now="2026-11-17T12:20:00Z", **kw)
    assert out["status"]["india-north"] == "awaiting-key"
    assert all(out["status"][k] == "live" for k in BASE)
    assert out["hours_processed"] == 6
    live = json.loads((site / "data" / "live.json").read_text())
    assert [l["id"] for l in live["locations"]][-1] == "india-north" and "history" not in live["locations"][-1]
    assert len(live["locations"][1]["forecast"]) == 24 and live["twin"]["hours"] == 6
    assert {p["id"] for p in live["twin"]["policies"]} == {"ours", "ours-milp", "greenest", "unaware", "ours-naive"}
    # the trained forecaster: uses the weather, learned that wind matters, and beats the naive methods on unseen days
    london = next(l for l in live["locations"] if l["id"] == "london")
    assert london["forecast_model"] == "weather-trees" and len(london["weather_effect"]) == 24 and len(london["weather"]) == 48
    card = live["models"]["forecaster"]["per_location"]["london"]
    assert card["has_weather"] and card["rows"] > 5000 and 40 <= card["rounds"] <= 500
    assert any("wind" in d["name"] for d in card["drivers"][:3])
    acc = live["accuracy"]["per_location"]["london"]
    assert acc["skill_pct"] > 20 and len(acc["by_horizon"]["ours"]) == 24 and acc["mae_ours"] < acc["mae_persistence"]
    assert card["val_mae"] < card["val_mae_persistence"] and card["train_mae"] < 3 * card["val_mae_trees"] + 5
    value = live["accuracy"]["forecast_value"]
    assert value is None or {"naive_g", "model_g", "perfect_g", "saved_pct", "perfect_pct", "streams"} <= set(value)
    # uncertainty: the band brackets the forecast and its hit rate on unseen days is reported, not assumed
    assert all(lo <= mid <= hi for _, lo, mid, hi in london["forecast"])
    rc = live["track"]["london"]["recal"]                           # band re-checked against forecasts that have come true
    assert rc["n"] > 100 and rc["hit_pct"] >= rc["model_band_hit_pct"] and rc["width"] >= rc["model_band_width"]
    assert set(live["track"]["london"]["widen_now"]) <= {"1", "3", "6", "12", "24"}
    assert 0 <= acc["band_hit_pct"] <= 100 and 0 < card["val_band_coverage"] <= 1 and card["band_coverage_target"] == 0.8
    # forecast log: back-filled on first start, the live row for this hour is on file, nothing live is scored yet
    log = pd.read_csv(site / "data" / "fc_log.csv")
    assert set(log["src"]) == {"backfill", "live"} and set(log["h"]) == {1, 3, 6, 12, 24}
    assert live["track"]["london"]["logged"] > 50 and live["track"]["london"]["live_scored"] == 0
    # anomaly detector ran over the back-filled log; the smooth fake grid gives it nothing to flag
    an = live["anomalies"]
    assert an["hours_checked"] > 200 and set(an["latest"]) == set(BASE) and an["alarm_rate_pct"] <= 1.5
    assert all(v["limit"] >= an["threshold"] for v in an["per_location"].values())
    assert set(live["cost_model"]) >= {"checkpoint", "network_kwh_per_gb", "source"}
    first_totals = dict(out["totals"])

    again = tick(site, now="2026-11-17T12:40:00Z", **kw)            # same hour: nothing new to schedule
    assert again["hours_processed"] == 0 and again["totals"] == first_totals

    later = tick(site, now="2026-11-17T14:05:00Z", **kw)            # two more completed hours
    assert later["hours_processed"] == 2
    live2 = json.loads((site / "data" / "live.json").read_text())
    assert live2["twin"]["hours"] == 8 and live2["meta"]["ticks"] == 3
    t2 = live2["track"]["london"]                                   # the forecast issued for the 11:00 hour has now been checked
    assert t2["live_scored"] >= 1 and t2["since"] == "2026-11-17T11:00:00Z" and t2["mae"] >= 0
    log2 = pd.read_csv(site / "data" / "fc_log.csv")
    assert not log2.duplicated(["issued", "location", "h"]).any()
    series = live2["twin"]["series"]
    for col in range(1, 6):
        vals = [r[col] for r in series]
        assert vals == sorted(vals)                                   # cumulative carbon never decreases
    assert all(later["totals"][k] >= first_totals[k] for k in first_totals)
    assert (site / ".nojekyll").exists() and (site / "data" / "ci_hourly.csv").exists()


def test_empty_feed_is_reported_as_no_data(small_cfg, tmp_path):
    def empty_france(loc, start, end, session):
        if loc["id"] == "france":
            return pd.DataFrame({"timestamp": pd.to_datetime([], utc=True), "ci": []})
        return fake_source(loc, start, end, session)
    out = tick(tmp_path / "site", now="2026-11-17T12:20:00Z", config_path=small_cfg, forward={}, web_dir=tmp_path / "noweb", weather_fetcher=fake_weather,
               sources={k: empty_france for k in ("gb-regional", "energidata", "rte-eco2mix", "electricity-maps")}, log=lambda *_: None)
    assert out["status"]["france"] == "no-data" and out["rows"]["france"] == 0
    assert out["status"]["london"] == "live" and out["rows"]["london"] > 100
    live = json.loads((tmp_path / "site" / "data" / "live.json").read_text())
    milp = next(p for p in live["twin"]["policies"] if p["id"] == "ours-milp")
    assert milp["solver_fallbacks"] == 0                      # the optimiser really ran


def test_state_version_bump_rebuilds_twin(small_cfg, tmp_path):
    site = tmp_path / "site"
    kw = dict(config_path=small_cfg, sources={k: fake_source for k in ("gb-regional", "energidata", "rte-eco2mix", "electricity-maps")},
              forward={}, web_dir=tmp_path / "noweb", weather_fetcher=fake_weather, log=lambda *_: None)
    tick(site, now="2026-11-17T12:20:00Z", **kw)
    st = site / "data" / "state.json"
    old = json.loads(st.read_text()); old["version"] = 1; st.write_text(json.dumps(old))
    out = tick(site, now="2026-11-17T13:20:00Z", **kw)
    assert out["hours_processed"] == 6                         # rebuilt from recorded data, not continued


def test_weather_model_falls_back_without_enough_history():
    from cao.forecast.weather_blend import MIN_HOURS, WeatherBlendForecaster
    short = pd.Series(np.linspace(100, 200, MIN_HOURS - 1), index=pd.date_range("2026-10-01", periods=MIN_HOURS - 1, freq="1h", tz="UTC"))
    with pytest.raises(ValueError):
        WeatherBlendForecaster().fit(short)


def test_weather_model_monotone_in_wind_and_works_without_weather():
    from cao.forecast.weather_blend import WeatherBlendForecaster
    idx = pd.date_range("2026-09-01", periods=24 * 45, freq="1h", tz="UTC")
    wind = pd.Series(3 + 10 * _windiness(idx), index=idx)
    ci = pd.Series(300 - 18 * wind.values + 20 * np.sin(2 * np.pi * idx.hour / 24), index=idx)
    wx = pd.DataFrame({"wind": wind, "wind_max": wind + 1, "wind3": np.minimum(wind, 13) ** 3, "solar": 0.0, "temp": 10.0, "cloud": 50.0})
    m = WeatherBlendForecaster().fit(ci, wx)
    calm, windy = wx.copy(), wx.copy()
    future = calm.index > ci.index[-1] - pd.Timedelta(hours=1)
    hist, wx_long = ci.iloc[:-30], wx
    lo_wind = wx_long.copy(); lo_wind.loc[lo_wind.index > hist.index[-1], ["wind", "wind_max"]] = 2.0; lo_wind["wind3"] = np.minimum(lo_wind["wind"], 13) ** 3
    hi_wind = wx_long.copy(); hi_wind.loc[hi_wind.index > hist.index[-1], ["wind", "wind_max"]] = 13.0; hi_wind["wind3"] = np.minimum(hi_wind["wind"], 13) ** 3
    assert m.predict(hist, hi_wind)[12:].mean() < m.predict(hist, lo_wind)[12:].mean()      # more wind, cleaner forecast
    plain = WeatherBlendForecaster().fit(ci)                                                  # no weather table at all
    assert plain.predict(hist).shape == (24,) and not plain.diag["has_weather"]


def test_uncertainty_band_is_calibrated_and_brackets_the_forecast():
    from cao.forecast.weather_blend import WeatherBlendForecaster
    rng = np.random.default_rng(3)
    idx = pd.date_range("2026-08-01", periods=24 * 60, freq="1h", tz="UTC")
    wind = pd.Series(3 + 10 * _windiness(idx), index=idx)
    noise = np.cumsum(rng.normal(0, 4, len(idx))); noise -= np.linspace(0, noise[-1], len(idx))
    ci = pd.Series(300 - 18 * wind.values + 20 * np.sin(2 * np.pi * idx.hour / 24) + noise, index=idx)
    wx = pd.DataFrame({"wind": wind, "wind_max": wind + 1, "wind3": np.minimum(wind, 13) ** 3, "solar": 0.0, "temp": 10.0, "cloud": 50.0})
    m = WeatherBlendForecaster().fit(ci.iloc[:-24 * 10], wx)
    assert 0.6 <= m.diag["val_band_coverage"] <= 0.95                # near the 80 % target on held-out days
    hits = n = 0
    for k in range(10):                                             # ten later days the model never saw
        cut = len(ci) - 24 * (10 - k)
        p = m.predict_parts(ci.iloc[:cut], wx, explain=False)
        truth = ci.iloc[cut:cut + 24].values
        assert (p["lo"] <= p["p50"] + 1e-9).all() and (p["p50"] <= p["hi"] + 1e-9).all()
        hits += int(((truth >= p["lo"]) & (truth <= p["hi"])).sum()); n += len(truth)
    assert 0.55 <= hits / n <= 0.97                                 # neither uselessly wide nor falsely narrow
    assert np.mean(p["hi"][12:] - p["lo"][12:]) > np.mean(p["hi"][:3] - p["lo"][:3])     # less sure further ahead


def _scored(spike=None, n=24 * 10, loc="london"):
    """A scored 3-hour-ahead forecast log: small errors, optionally one big miss."""
    rng = np.random.default_rng(1)
    target = pd.date_range("2026-11-07", periods=n, freq="1h", tz="UTC")
    p50 = np.full(n, 200.0)
    actual = p50 + rng.normal(0, 6, n)
    if spike is not None:
        actual[spike[0]:spike[1]] += spike[2]
    return pd.DataFrame({"issued": target - pd.Timedelta(hours=3), "location": loc, "h": 3, "target": target, "p50": p50,
                         "lo": p50 - 15, "hi": p50 + 15, "model": "weather-trees", "src": "live", "actual": actual})


def test_anomaly_detector_flags_big_misses_and_explains_them_with_wind():
    from cao.live.anomaly import detect
    quiet = _scored()
    last = quiet["target"].max()
    out = detect(quiet, {}, last)
    assert out["events"] == [] and out["hours_checked"] == len(quiet) and not out["latest"]["london"]["unusual"]

    spiky = _scored(spike=(-5, -2, 90.0))                            # three hours far dirtier than forecast
    idx = pd.date_range(spiky["target"].min(), last, freq="1h")
    wx = pd.DataFrame({"wind": 9.0, "wind_obs": 9.0}, index=idx)
    wx.loc[spiky["target"].iloc[-5:-2], "wind_obs"] = 4.0            # the wind dropped when the grid got dirty
    out = detect(spiky, {"london": wx}, last)
    assert len(out["events"]) == 1
    ev = out["events"][0]
    assert ev["direction"] == "dirtier" and ev["hours"] == 3 and ev["z"] > 3 and ev["why"]["kind"] == "wind"
    assert ev["actual"] > ev["band"][1] and out["per_location"]["london"]["flagged"] == 3
    calm = detect(spiky, {"london": wx.assign(wind_obs=9.0)}, last)  # same miss, wind as forecast: blame something else
    assert calm["events"][0]["why"]["kind"] == "other"
    clean = detect(_scored(spike=(-1, None, -90.0)), {}, last)       # cleaner than expected, still under way
    assert clean["events"][0]["direction"] == "cleaner" and clean["events"][0]["ongoing"] and clean["latest"]["london"]["unusual"]


def test_forecast_log_is_idempotent_and_scored_against_what_happened(tmp_path):
    from cao.live.store import LiveStore
    from cao.live.track import log_forecasts, score_log, track_summary
    store = LiveStore(tmp_path)
    t0 = pd.Timestamp("2026-11-17T00:00:00Z")
    idx = pd.date_range(t0 - pd.Timedelta(hours=2), periods=40, freq="1h")
    filled = pd.DataFrame({"london": np.linspace(100, 139, 40)}, index=idx)
    pred = {"london": {"p50": np.full(24, 110.0), "lo": np.full(24, 100.0), "hi": np.full(24, 120.0), "model": "weather-trees"}}
    assert log_forecasts(store, t0, pred) == 5
    assert log_forecasts(store, t0, pred) == 0                      # a second run in the same hour adds nothing
    assert score_log(store, filled, t0).empty                       # nothing has come true yet
    sc = score_log(store, filled, t0 + pd.Timedelta(hours=6))
    assert list(sc["h"]) == [1, 3, 6]
    assert list(sc["actual"]) == [103.0, 105.0, 108.0] and list(sc["naive"]) == [102.0] * 3
    assert list(sc["err"]) == [7.0, 5.0, 2.0] and sc["inside"].all()
    summ = track_summary(sc)["london"]
    assert summ["live_scored"] == 3 and summ["mae"] == 4.7 and summ["naive_mae"] == 3.3 and summ["band_hit_pct"] == 100.0


def test_band_is_widened_from_checked_forecasts_only_and_never_narrowed():
    from cao.live.track import RECAL_MIN, apply_widening, band_widening, recalibrate
    rng = np.random.default_rng(5)
    n = 24 * 12
    issued = pd.date_range("2026-11-01", periods=n, freq="1h", tz="UTC")
    def log(h, half, sigma):
        actual = 200 + rng.normal(0, sigma, n)
        return pd.DataFrame({"issued": issued, "location": "london", "h": h, "target": issued + pd.Timedelta(hours=h), "p50": 200.0,
                             "lo": 200.0 - half, "hi": 200.0 + half, "model": "weather-trees", "src": "backfill", "actual": actual,
                             "inside": np.abs(actual - 200) <= half})
    sc = recalibrate(pd.concat([log(3, 5.0, 10.0), log(24, 40.0, 10.0)], ignore_index=True))    # 3 h band far too narrow, 24 h band generous
    narrow, wide = sc[sc["h"] == 3], sc[sc["h"] == 24]
    assert not narrow["calibrated"].iloc[:RECAL_MIN].any() and (narrow["widen"].iloc[:RECAL_MIN] == 0).all()     # no history, no adjustment
    cal = narrow[narrow["calibrated"]]
    assert cal["inside"].mean() < 0.5 and 0.7 <= cal["inside_adj"].mean() <= 0.9                # pulled to the 80 % aim
    assert (wide["widen"] == 0).all() and (wide["lo_adj"] == wide["lo"]).all()                  # a band that already holds is left alone
    at = issued[-1] + pd.Timedelta(hours=1)
    w = band_widening(sc, at)
    assert w["london"][3] > 5 and w["london"][24] == 0
    later = sc.assign(actual=sc["actual"] + 500.0)                                              # only forecasts already checked may count
    assert band_widening(later[later["target"] > at], at) == {}
    preds = {"london": {"p50": np.full(24, 200.0), "lo": np.full(24, 195.0), "hi": np.full(24, 205.0)}, "france": {"p50": np.full(24, 30.0), "lo": None, "hi": None}}
    apply_widening(preds, w)
    p = preds["london"]
    assert (p["lo_raw"] == 195).all() and p["lo"][0] == 195 and p["lo"][2] == 195 - w["london"][3] and p["hi"][1] == 205 + w["london"][3] and p["hi"][23] == 205
    assert preds["france"]["lo"] is None


def test_anomaly_alarm_line_rises_on_a_heavy_tailed_grid():
    from cao.live.anomaly import THRESHOLD, detect
    rng = np.random.default_rng(2)
    calm, jumpy = _scored(loc="london"), _scored(loc="south-wales")
    wild = rng.random(len(jumpy)) < 0.08                                                        # one hour in twelve is a big miss: normal for this grid
    jumpy.loc[wild, "actual"] += rng.choice([-1, 1], wild.sum()) * rng.uniform(40, 70, wild.sum())
    out = detect(pd.concat([calm, jumpy], ignore_index=True), {}, calm["target"].max())
    per = out["per_location"]
    assert per["london"]["limit"] == THRESHOLD and per["south-wales"]["limit"] > 2 * THRESHOLD
    assert per["south-wales"]["flagged"] <= 0.02 * per["south-wales"]["hours_checked"] + 1       # about one hour in a hundred, not one in twelve
