import numpy as np
import pandas as pd

from cao.carbon.emission_factors import EIA_MAP, ci_from_mix
from cao.carbon.schema import normalize, strip_index, to_traces
from cao.carbon.sources.synthetic import generate_dataset
from cao.forecast import GradientBoostingForecaster, PersistenceForecaster, SeasonalNaiveForecaster, backtest, make_supervised


def test_ci_from_mix():
    assert np.isclose(ci_from_mix({"NUC": 100, "WND": 100}, EIA_MAP), (12 + 11) / 2)
    assert np.isclose(ci_from_mix({"coal": 50, "gas": 50}), (820 + 490) / 2)


def test_normalize_hourly_and_gap_fill():
    ts = pd.date_range("2026-01-01", periods=6, freq="30min", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "ci_g_per_kwh": [100, 120, np.nan, np.nan, 200, 220]})
    out = normalize(df, "uk", "test")
    assert list(out.columns) == ["timestamp", "region", "ci_g_per_kwh", "source"]
    assert len(out) == 3 and np.isclose(out["ci_g_per_kwh"].iloc[0], 110)


def test_to_traces_aligns_regions():
    df = generate_dataset(["india", "sweden"], days=2)
    tr = strip_index(to_traces(df, hours=30))
    assert set(tr) == {"india", "sweden"} and len(tr["india"]) == 30
    assert tr["india"].mean() > tr["sweden"].mean()


def test_supervised_shapes():
    s = pd.Series(np.arange(300, dtype=float))
    X, y = make_supervised(s, range(1, 4))
    assert len(X) == len(y) == 299 + 298 + 297 and "h" in X.columns


def test_forecasters_and_backtest():
    df = generate_dataset(["uk"], days=21, seed=1)
    s = df.set_index("timestamp")["ci_g_per_kwh"]
    assert PersistenceForecaster().predict(s, 24).shape == (24,)
    assert SeasonalNaiveForecaster().predict(s, 24).shape == (24,)
    gb = GradientBoostingForecaster(max_horizon=6).fit(s)
    lo, pt, hi = gb.predict_interval(s, 6)
    assert pt.shape == (6,) and (hi >= pt).all() and (pt >= lo).all()
    bt = backtest(lambda: PersistenceForecaster(), s, horizon=6, n_origins=5, min_train=24 * 7)
    assert list(bt.columns) == ["model", "h", "mae", "mape_pct"] and len(bt) == 6
