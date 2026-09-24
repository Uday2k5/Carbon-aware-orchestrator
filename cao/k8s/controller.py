"""Kubernetes controller loop: pods -> Jobs -> DecisionEngine -> MOVE via nodeSelector patch."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

from ..core.models import ActionType, Decision, Job
from ..decision.engine import DecisionEngine
from . import constants as C
from .client import KubeClient, PodInfo
from .migrate import migrate

CIProvider = Callable[[], Dict[str, Sequence[float]]]   # region -> forecast from now (slot 0 = now)


class Controller:
    def __init__(
        self,
        kube: KubeClient,
        engine: DecisionEngine,
        ci_provider: CIProvider,
        db=None,
        mode: str = "heuristic",
        dry_run: bool = False,
        checkpoints_dir: Optional[str] = None,
        namespace: Optional[str] = None,
        migration_timeout_s: float = 900.0,
        epoch: Optional[datetime] = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self.kube = kube
        self.engine = engine
        self.ci_provider = ci_provider
        self.db = db
        self.mode = mode
        self.dry_run = dry_run
        self.checkpoints_dir = checkpoints_dir
        self.namespace = namespace
        self.migration_timeout_s = migration_timeout_s
        self.epoch = epoch or datetime.now(timezone.utc)
        self.log = log
        self.history: List[dict] = []

    # ------------------------------------------------------------- mapping
    def now_h(self) -> float:
        return (datetime.now(timezone.utc) - self.epoch).total_seconds() / 3600.0

    def job_from_pod(self, pod: PodInfo) -> Optional[Job]:
        a = pod.annotations
        region = self.kube.node_region(pod.node) if pod.node else None
        if region is None:
            return None
        deadline = a.get(C.ANN_DEADLINE)
        deadline_h = None
        if deadline:
            dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            deadline_h = (dl - self.epoch).total_seconds() / 3600.0
        kind = a.get(C.ANN_KIND, "batch-processing")
        remaining = float(a.get(C.ANN_REMAINING_H, self.engine.evaluation_horizon_h))
        return Job(
            job_id=pod.deployment or pod.name, kind=kind,
            power_kw=float(a.get(C.ANN_POWER_KW, 0.05)),
            duration_h=remaining, state_gb=float(a.get(C.ANN_STATE_GB, 0.1)),
            origin=region, region=region, deadline_h=deadline_h,
            user_region=a.get(C.ANN_USER_REGION), 
            sla_rtt_ms=float(a[C.ANN_SLA_RTT_MS]) if C.ANN_SLA_RTT_MS in a else None,
            preemptible=a.get(C.ANN_PREEMPTIBLE, "true").lower() == "true",
            movable=a.get(C.ANN_MOVABLE, "true").lower() == "true",
            cpu=float(a.get(C.ANN_CPU, 1.0)),
            started=True, running=pod.phase == "Running",
            tags={"pod": pod.name, "namespace": pod.namespace},
        )

    # ---------------------------------------------------------------- tick
    def tick(self) -> List[Decision]:
        pods = [p for p in self.kube.list_managed_pods(self.namespace) if p.phase == "Running"]
        jobs, by_id = [], {}
        for p in pods:
            j = self.job_from_pod(p)
            if j is not None:
                jobs.append(j)
                by_id[j.job_id] = (j, p)
        if not jobs:
            self.log("no managed running pods")
            return []
        ci = self.ci_provider()
        now_h = self.now_h()
        decisions = self.engine.decide(jobs, ci, now_h, mode=self.mode)
        out = []
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for jid, d in decisions.items():
            job, pod = by_id[jid]
            applied = False
            self.log(f"{jid:<24} {d.action.value:<7} {d.target_region or '-':<10} {d.reason}")
            if d.action == ActionType.MOVE and not self.dry_run:
                rec = migrate(self.kube, pod, d.target_region, job.state_gb, self.checkpoints_dir,
                              self.migration_timeout_s, from_region=job.region)
                applied = rec.success
                self.history.append(rec.to_dict())
                if self.db is not None:
                    self.db.insert_migration(rec.to_dict())
            if not self.dry_run:
                try:
                    self.kube.annotate_pod(pod.name, pod.namespace,
                                           {C.ANN_LAST_DECISION: f"{stamp} {d.action.value} {d.reason}"[:250]})
                except Exception:  # pod may already be gone after a MOVE
                    pass
            if self.db is not None:
                self.db.insert_decision(d, job.region, self.mode, applied, stamp)
            out.append(d)
        return out

    def run(self, interval_s: float = 300.0, max_ticks: Optional[int] = None) -> None:
        n = 0
        while max_ticks is None or n < max_ticks:
            try:
                self.tick()
            except Exception as exc:  # keep the loop alive
                self.log(f"tick failed: {exc!r}")
            n += 1
            if max_ticks is not None and n >= max_ticks:
                break
            time.sleep(interval_s)
