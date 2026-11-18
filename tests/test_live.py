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
    assert value is None or {"naive_g", "model_g", "perfect_g"} <= set(value)
    assert set(live["cost_model"]) >= {"checkpoint", "network_kwh_per_gb", "source"}
    first_totals = dict(out["totals"])

    again = tick(site, now="2026-11-17T12:40:00Z", **kw)            # same hour: nothing new to schedule
    assert again["hours_processed"] == 0 and again["totals"] == first_totals

    later = tick(site, now="2026-11-17T14:05:00Z", **kw)            # two more completed hours
    assert later["hours_processed"] == 2
    live2 = json.loads((site / "data" / "live.json").read_text())
    assert live2["twin"]["hours"] == 8 and live2["meta"]["ticks"] == 3
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
