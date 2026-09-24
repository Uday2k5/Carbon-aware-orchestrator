import numpy as np
import pandas as pd

from cao.migration.cost_model import LinearPhase, MigrationCostModel


def test_breakdown_sums(cost_model):
    mc = cost_model.carbon_g(2.0, 500, 100)
    assert np.isclose(mc.total_g, mc.checkpoint_g + mc.transfer_g + mc.network_g + mc.restore_g)
    assert mc.network_g > 0 and mc.downtime_s > cost_model.downtime_base_s


def test_network_attribution_modes():
    kw = dict(checkpoint=LinearPhase(0, 0), transfer=LinearPhase(0, 0), restore=LinearPhase(0, 0),
              network_kwh_per_gb=1.0)
    assert np.isclose(MigrationCostModel(network_ci_attribution="src", **kw).carbon_g(1, 600, 100).total_g, 600)
    assert np.isclose(MigrationCostModel(network_ci_attribution="dst", **kw).carbon_g(1, 600, 100).total_g, 100)
    assert np.isclose(MigrationCostModel(network_ci_attribution="mean", **kw).carbon_g(1, 600, 100).total_g, 350)


def test_fit_recovers_line():
    sizes = np.array([0.1, 0.5, 1, 5, 10, 20])
    df = pd.DataFrame({
        "state_gb": sizes,
        "checkpoint_j": 60 * sizes + 5, "transfer_j": 120 * sizes + 8, "restore_j": 50 * sizes + 4,
        "checkpoint_s": 2 * sizes + 0.5, "transfer_s": 1.5 * sizes + 0.3, "restore_s": 1 * sizes + 0.2,
    })
    cm = MigrationCostModel.fit(df, network_kwh_per_gb=0.06)
    assert np.isclose(cm.checkpoint.a, 60) and np.isclose(cm.checkpoint.b, 5)
    assert np.isclose(cm.transfer.a, 120) and np.isclose(cm.restore.a, 50)
    assert np.isclose(cm.downtime_per_gb_s, 4.5) and np.isclose(cm.downtime_base_s, 1.0)
    assert cm.fit_stats["checkpoint"]["r2"] > 0.999
    assert cm.source.startswith("measured")


def test_json_roundtrip(tmp_path, cost_model):
    p = tmp_path / "m.json"
    cost_model.to_json(p)
    back = MigrationCostModel.from_json(p)
    assert back.carbon_g(3, 400, 50).total_g == cost_model.carbon_g(3, 400, 50).total_g


def test_departure_plus_arrival_equals_total(cost_model):
    import copy
    for mode in ("mean", "src", "dst"):
        cm = copy.deepcopy(cost_model)
        cm.network_ci_attribution = mode
        for s_gb, a, b in ((0.2, 650, 50), (60, 400, 380), (5, 100, 700)):
            assert np.isclose(cm.departure_carbon_g(s_gb, a) + cm.arrival_carbon_g(s_gb, b),
                              cm.carbon_g(s_gb, a, b).total_g)
