import json

import numpy as np
import pandas as pd
import pytest
import yaml

from cao.live.config import load_live_config
from cao.live.pipeline import tick
from cao.live.sources import MissingKey, to_hourly

BASE = {"north-west-england": 60, "london": 200, "south-wales": 330, "denmark-west": 110, "france": 40}


def fake_source(loc, start, end, session):
    if loc["id"] not in BASE:
        raise MissingKey("ELECTRICITY_MAPS_TOKEN")
    ts = pd.date_range(pd.Timestamp(start).floor("30min"), pd.Timestamp(end), freq="30min")
    phase = (sum(map(ord, loc["id"])) % 24) / 24 * 2 * np.pi
    wob = 0.3 * np.sin(2 * np.pi * ts.hour / 24 + phase) + 0.1 * np.sin(2 * np.pi * ts.dayofyear / 5 + phase)
    return pd.DataFrame({"timestamp": ts, "ci": BASE[loc["id"]] * (1 + wob)})


@pytest.fixture(scope="module")
def small_cfg(tmp_path_factory):
    cfg = load_live_config().raw
    cfg = dict(cfg, backfill_days=12, warm_start_hours=6)
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
              forward={}, web_dir=tmp_path / "noweb", log=lambda *_: None)
    out = tick(site, now="2026-11-17T12:20:00Z", **kw)
    assert out["status"]["india-north"] == "awaiting-key"
    assert all(out["status"][k] == "live" for k in BASE)
    assert out["hours_processed"] == 6
    live = json.loads((site / "data" / "live.json").read_text())
    assert [l["id"] for l in live["locations"]][-1] == "india-north" and "history" not in live["locations"][-1]
    assert len(live["locations"][1]["forecast"]) == 24 and live["twin"]["hours"] == 6
    assert {p["id"] for p in live["twin"]["policies"]} == {"ours", "ours-milp", "greenest", "unaware"}
    assert set(live["cost_model"]) >= {"checkpoint", "network_kwh_per_gb", "source"}
    first_totals = dict(out["totals"])

    again = tick(site, now="2026-11-17T12:40:00Z", **kw)            # same hour: nothing new to schedule
    assert again["hours_processed"] == 0 and again["totals"] == first_totals

    later = tick(site, now="2026-11-17T14:05:00Z", **kw)            # two more completed hours
    assert later["hours_processed"] == 2
    live2 = json.loads((site / "data" / "live.json").read_text())
    assert live2["twin"]["hours"] == 8 and live2["meta"]["ticks"] == 3
    series = live2["twin"]["series"]
    for col in range(1, 5):
        vals = [r[col] for r in series]
        assert vals == sorted(vals)                                   # cumulative carbon never decreases
    assert all(later["totals"][k] >= first_totals[k] for k in first_totals)
    assert (site / ".nojekyll").exists() and (site / "data" / "ci_hourly.csv").exists()
