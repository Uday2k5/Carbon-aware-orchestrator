import math

from cao.core.units import joules_to_kwh
from cao.decision.payback import carbon_rate_g_per_h, payback_boundary, payback_hours, saved_carbon_g


def test_units():
    assert joules_to_kwh(3_600_000) == 1.0


def test_plan_example_one_hour():
    # migration 500 g, current 600 g/h, destination 100 g/h -> 1 h
    assert payback_hours(500, 600, 100) == 1.0


def test_ci_example_two_hours():
    # 0.5 kWh/h, 600 -> 150 g/kWh, migration 450 g -> 2 h
    rate_src = carbon_rate_g_per_h(0.5, 600)
    rate_dst = carbon_rate_g_per_h(0.5, 150)
    assert math.isclose(payback_hours(450, rate_src, rate_dst), 2.0)


def test_never_pays_back_when_destination_dirtier():
    assert payback_hours(10, 100, 200) == math.inf


def test_saved_carbon_with_forecast_sequences():
    src = [600, 500, 400]
    dst = [100, 100, 100]
    # 1 kW, 2.5 h: 500 + 400 + 0.5*300
    assert math.isclose(saved_carbon_g(1.0, src, dst, 2.5), 1050.0)


def test_boundary_monotone_in_state_size(cost_model):
    pts = payback_boundary(0.2, 650, 50, [0.1, 1, 10, 60], cost_model)
    pb = [p.payback_h for p in pts]
    assert pb == sorted(pb)
    assert pts[-1].migration_g > pts[0].migration_g
