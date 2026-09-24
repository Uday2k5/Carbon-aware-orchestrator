from cao.core.models import ActionType, Job
from cao.decision.simple import decide_simple
from cao.simulator.workloads import plan_examples


def test_job_a_moves_and_job_b_refuses(cost_model):
    ci = {"india": 650.0, "sweden": 50.0}
    a, b = plan_examples()
    da = decide_simple(a, ci, cost_model)
    db = decide_simple(b, ci, cost_model)
    assert da.action == ActionType.MOVE and da.target_region == "sweden"
    assert da.saved_g > da.migration_g
    assert db.action == ActionType.REFUSE
    assert db.migration_g > db.saved_g
    assert db.payback_h > b.remaining_h


def test_hold_when_no_greener_region(cost_model):
    j = Job("j", "batch-processing", 0.1, 3, 1, "sweden", running=True, started=True)
    d = decide_simple(j, {"sweden": 40.0, "india": 650.0}, cost_model)
    assert d.action == ActionType.HOLD


def test_allowed_regions_filter(cost_model):
    j = Job("j", "batch-processing", 0.1, 3, 1, "india", running=True, started=True)
    d = decide_simple(j, {"india": 650.0, "sweden": 40.0, "france": 60.0}, cost_model,
                      allowed_regions=["india", "france"])
    assert d.action == ActionType.MOVE and d.target_region == "france"


def test_margin_turns_move_into_refuse(cost_model):
    j = Job("j", "batch-processing", 0.1, 1, 1, "india", running=True, started=True)
    ci = {"india": 650.0, "sweden": 40.0}
    assert decide_simple(j, ci, cost_model).action == ActionType.MOVE
    assert decide_simple(j, ci, cost_model, margin_g=1e6).action == ActionType.REFUSE
