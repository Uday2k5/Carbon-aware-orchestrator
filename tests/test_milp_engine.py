from cao.core.models import ActionType, Job
from cao.decision.engine import DecisionEngine
from cao.decision.milp import plan_to_decisions, solve_milp
from cao.simulator.workloads import plan_examples

REGIONS = ["india", "sweden"]
FLAT = {"india": [650.0] * 6, "sweden": [50.0] * 6}
LAT = {"india": {"india": 20, "sweden": 150}, "sweden": {"india": 150, "sweden": 10}}


def test_milp_moves_small_state_and_keeps_large_state(cost_model):
    a, b = plan_examples()
    res = solve_milp([a, b], REGIONS, FLAT, cost_model, horizon=6)
    assert res.status == "Optimal"
    assert res.plan["job-A"][:2] == ["sweden", "sweden"]      # 2 h job runs immediately in Sweden
    assert res.plan["job-B"][0] == "india"                     # 60 GB state stays
    dec = plan_to_decisions(res, [a, b], FLAT, cost_model, REGIONS)
    assert dec["job-A"].action == ActionType.MOVE
    assert dec["job-B"].action == ActionType.REFUSE


def test_milp_respects_sla_and_capacity(cost_model):
    web = Job("web", "web-service", 0.05, 6, 0.1, "india", user_region="india", sla_rtt_ms=50,
              running=True, started=True)
    res = solve_milp([web], REGIONS, FLAT, cost_model, latency_ms=LAT, horizon=6)
    assert all(r == "india" for r in res.plan["web"])
    j1 = Job("j1", "batch-processing", 0.1, 6, 0.1, "india", cpu=2, running=True, started=True)
    j2 = Job("j2", "batch-processing", 0.1, 6, 0.1, "india", cpu=2, running=True, started=True)
    res = solve_milp([j1, j2], REGIONS, FLAT, cost_model, capacity={"sweden": 2, "india": 10}, horizon=6)
    for t in range(6):
        assert sum(1 for j in ("j1", "j2") if res.plan[j][t] == "sweden") <= 1


def test_milp_waits_for_cleaner_window(cost_model):
    fc = {"india": [600, 580, 520, 400, 250, 180, 170, 200], "sweden": [600] * 8}
    p = Job("p", "batch-processing", 0.1, 2, 1, "india", deadline_h=8)
    res = solve_milp([p], REGIONS, fc, cost_model, horizon=8)
    assert res.plan["p"] == [None] * 5 + ["india", "india", None]
    d = plan_to_decisions(res, [p], fc, cost_model, REGIONS)["p"]
    assert d.action == ActionType.WAIT and d.resume_at_h == 5.0


def test_engine_heuristic_and_milp_agree_on_plan_examples(cost_model):
    eng = DecisionEngine(cost_model, REGIONS)
    for mode in ("heuristic", "milp"):
        a, b = plan_examples()
        out = eng.decide([a, b], FLAT, mode=mode)
        assert out["job-A"].action == ActionType.MOVE
        assert out["job-B"].action == ActionType.REFUSE


def test_engine_wait_disabled(cost_model):
    fc = {"india": [600, 580, 520, 400, 250, 180, 170, 200], "sweden": [590] * 8}
    p = Job("p", "batch-processing", 0.1, 2, 1, "india", deadline_h=8)
    assert DecisionEngine(cost_model, REGIONS, allow_wait=True).decide_one(p, fc).action == ActionType.WAIT
    assert DecisionEngine(cost_model, REGIONS, allow_wait=False).decide_one(p, fc).action != ActionType.WAIT
