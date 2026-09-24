from cao.decision.engine import DecisionEngine
from cao.k8s import constants as C
from cao.k8s.client import FakeKubeClient, PodInfo
from cao.k8s.controller import Controller
from cao.k8s.migrate import migrate

NODES = {"node-india": "india", "node-sweden": "sweden"}


def pods():
    return [
        PodInfo("ml-training-1", "cao", "node-india",
                labels={C.MANAGED_LABEL: "true", C.DEPLOYMENT_LABEL: "ml-training"},
                annotations={C.ANN_KIND: "ml-training", C.ANN_POWER_KW: "0.2",
                             C.ANN_STATE_GB: "0.2", C.ANN_REMAINING_H: "2"}),
        PodInfo("big-1", "cao", "node-india",
                labels={C.MANAGED_LABEL: "true", C.DEPLOYMENT_LABEL: "big"},
                annotations={C.ANN_KIND: "ml-training", C.ANN_POWER_KW: "0.2",
                             C.ANN_STATE_GB: "60", C.ANN_REMAINING_H: "0.5"}),
        PodInfo("web-1", "cao", "node-india",
                labels={C.MANAGED_LABEL: "true", C.DEPLOYMENT_LABEL: "web"},
                annotations={C.ANN_KIND: "web-service", C.ANN_POWER_KW: "0.05", C.ANN_STATE_GB: "0.1",
                             C.ANN_USER_REGION: "india", C.ANN_SLA_RTT_MS: "50"}),
    ]


def test_controller_moves_only_when_payback_is_met(cost_model):
    kube = FakeKubeClient(pods(), NODES)
    lat = {"india": {"india": 20, "sweden": 150}, "sweden": {"india": 150, "sweden": 10}}
    engine = DecisionEngine(cost_model, ["india", "sweden"], lat)
    ci = lambda: {"india": [650.0] * 24, "sweden": [50.0] * 24}
    ctl = Controller(kube, engine, ci, log=lambda *_: None)
    decisions = {d.job_id: d for d in ctl.tick()}
    assert decisions["ml-training"].action.value == "MOVE"
    assert decisions["big"].action.value == "REFUSE"
    assert decisions["web"].action.value == "HOLD"          # SLA forbids Sweden
    assert kube.patches == [("cao", "ml-training", "sweden")]
    assert kube.pods[("cao", "ml-training-1")].node == "node-sweden"
    assert ctl.history and ctl.history[0]["success"]


def test_dry_run_patches_nothing(cost_model):
    kube = FakeKubeClient(pods(), NODES)
    engine = DecisionEngine(cost_model, ["india", "sweden"])
    ctl = Controller(kube, engine, lambda: {"india": [650.0] * 24, "sweden": [50.0] * 24},
                     dry_run=True, log=lambda *_: None)
    ctl.tick()
    assert kube.patches == []


def test_migrate_record():
    kube = FakeKubeClient(pods(), NODES)
    rec = migrate(kube, pods()[0], "sweden", 0.2, from_region="india")
    assert rec.success and rec.to_region == "sweden" and rec.total_s >= 0
