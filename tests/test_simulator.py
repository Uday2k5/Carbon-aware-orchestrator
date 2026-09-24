import numpy as np

from cao.carbon.sources.synthetic import generate_trace
from cao.simulator import (
    CarbonUnawarePolicy, GreenestRegionPolicy, MigrationAwarePolicy, MilpPolicy, MoveOnlyPolicy,
    NoisyForecast, OracleForecast, PersistenceForecast, SeasonalNaiveForecast, WaitOnlyPolicy,
    compare_policies, generate_jobs, oracle, run_simulation,
)

REGIONS = ["india", "sweden", "france", "us-east"]
LAT = {r: {q: (10 if r == q else 120) for q in REGIONS} for r in REGIONS}


def traces(hours=72, seed=0):
    return {r: generate_trace(r, hours, seed) for r in REGIONS}


def test_synthetic_traces_reproducible_across_processes():
    import subprocess, sys
    code = "from cao.carbon.sources.synthetic import generate_trace; print(generate_trace('uk', 5, 3).round(6).tolist())"
    a = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout
    b = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout
    assert a == b and a.strip()


def test_generate_jobs_reproducible():
    a = generate_jobs(10, REGIONS, 72, seed=3)
    b = generate_jobs(10, REGIONS, 72, seed=3)
    assert [j.job_id for j in a] == [j.job_id for j in b]
    assert {j.kind for j in a} <= {"ml-training", "batch-processing", "web-service"}


def test_forecast_providers_shapes():
    tr = traces(48)
    for fp in (OracleForecast(tr), NoisyForecast(tr, 0.1), PersistenceForecast(tr), SeasonalNaiveForecast(tr)):
        f = fp.forecast("india", 30, 24)
        assert f.shape == (24,) and np.all(f > 0)
        assert f[0] == tr["india"][30]      # now is always known exactly
    assert np.allclose(OracleForecast(tr).forecast("india", 40, 24)[:8], tr["india"][40:48])


def test_simulation_accounting_and_baselines(cost_model):
    tr = traces(72)
    jobs = generate_jobs(12, REGIONS, 72, seed=1)
    unaware = run_simulation(tr, jobs, CarbonUnawarePolicy(), cost_model, LAT)
    assert unaware.migrations == 0 and np.isclose(unaware.total_g, unaware.exec_g + unaware.migration_g + unaware.resume_g)
    assert unaware.total_g > 0
    greenest = run_simulation(tr, jobs, GreenestRegionPolicy(), cost_model, LAT)
    assert greenest.migrations > 0
    assert greenest.sla_violation_slots == 0                 # SLA respected even by naive policy
    aware = run_simulation(tr, jobs, MigrationAwarePolicy(), cost_model, LAT)
    assert aware.total_g < unaware.total_g                   # carbon-aware beats unaware
    assert aware.deadline_violations <= unaware.deadline_violations + 1


def test_compare_policies_table(cost_model):
    tr = traces(48)
    jobs = generate_jobs(8, REGIONS, 48, seed=2)
    pols = [CarbonUnawarePolicy(), WaitOnlyPolicy(), MoveOnlyPolicy(), MigrationAwarePolicy(),
            oracle(MigrationAwarePolicy(), tr)]
    df = compare_policies(tr, jobs, pols, cost_model, latency_ms=LAT, forecast=NoisyForecast(tr, 0.2))
    assert set(df["policy"]) == {"carbon-unaware", "wait-only", "move-only", "migration-aware", "oracle-migration-aware"}
    oracle_total = df.loc[df["policy"] == "oracle-migration-aware", "total_g"].iloc[0]
    assert df.loc[df["policy"] == "oracle-migration-aware", "regret_g"].iloc[0] == 0.0
    assert np.allclose(df["regret_g"], (df["total_g"] - oracle_total).round(1))
    assert df.loc[df["policy"] == "carbon-unaware", "total_g"].iloc[0] == df["total_g"].max()


def test_milp_policy_runs(cost_model):
    tr = traces(30)
    jobs = generate_jobs(4, REGIONS, 30, seed=5)
    res = run_simulation(tr, jobs, MilpPolicy(time_limit_s=5), cost_model, LAT, horizon_slots=12)
    assert res.total_g > 0
    pol = MilpPolicy(time_limit_s=5, replan_every=4)
    res4 = run_simulation(tr, jobs, pol, cost_model, LAT, horizon_slots=12)
    assert res4.total_g > 0 and len(pol.solve_times) < 30
    assert abs(res4.total_g - res.total_g) / res.total_g < 0.15     # cached plans stay close
