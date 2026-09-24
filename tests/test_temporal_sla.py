from cao.core.models import ActionType, Job
from cao.decision.sla import feasible_regions
from cao.decision.temporal import best_contiguous_window, cheapest_slots, decide_temporal

FC = [600, 580, 520, 400, 250, 180, 170, 200]
LAT = {"india": {"india": 20, "sweden": 150, "france": 130}}


def test_best_window():
    assert best_contiguous_window(FC, 2) == (5, 350)
    assert best_contiguous_window(FC, 2, latest_start=3) == (3, 650)


def test_cheapest_slots():
    slots, total = cheapest_slots(FC, 3)
    assert slots == [5, 6, 7] and total == 550


def test_wait_decision_respects_deadline():
    j = Job("w", "batch-processing", 0.1, 2, 1, "india", deadline_h=8)
    d = decide_temporal(j, FC, 0.0)
    assert d.action == ActionType.WAIT and d.resume_at_h == 5.0
    tight = Job("t", "batch-processing", 0.1, 2, 1, "india", deadline_h=2)
    assert decide_temporal(tight, FC, 0.0).action == ActionType.HOLD


def test_web_service_never_waits():
    j = Job("web", "web-service", 0.05, 24, 0.1, "india", user_region="india", sla_rtt_ms=50)
    assert decide_temporal(j, FC, 0.0).action == ActionType.HOLD


def test_sla_filters_regions():
    j = Job("web", "web-service", 0.05, 24, 0.1, "india", user_region="india", sla_rtt_ms=50)
    assert feasible_regions(j, ["india", "sweden", "france"], LAT) == ["india"]
    j.sla_rtt_ms = 140
    assert feasible_regions(j, ["india", "sweden", "france"], LAT) == ["india", "france"]
    batch = Job("b", "batch-processing", 0.1, 2, 1, "india")
    assert feasible_regions(batch, ["india", "sweden"], LAT) == ["india", "sweden"]
    batch.movable = False
    assert feasible_regions(batch, ["india", "sweden"], LAT) == ["india"]
