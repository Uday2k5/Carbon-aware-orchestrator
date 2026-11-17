"""Discrete-time simulator: hourly slots, real CI traces, measured migration cost model.

Every policy is charged the *true* carbon of what it did (execution at the true CI,
migration carbon from the cost model, checkpoint+restore on every start/resume), even when
the policy itself ignored those costs (that is the point of baseline 2).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..core.models import ActionType, Decision, Job
from ..decision.sla import rtt_ms
from .forecast_providers import ForecastProvider, OracleForecast
from .policies import Policy, SimContext
from .step import step_slot


@dataclass
class SimResult:
    policy: str
    forecast: str
    total_g: float
    exec_g: float
    migration_g: float
    resume_g: float
    migrations: int
    moves: int
    waits: int
    holds: int
    refuses: int
    deadline_violations: int
    unfinished: int
    sla_violation_slots: int
    capacity_rejections: int
    mean_completion_h: float
    jobs: List[Job] = field(default_factory=list, repr=False)
    decisions: List[dict] = field(default_factory=list, repr=False)
    timeline: List[dict] = field(default_factory=list, repr=False)   # one snapshot per slot

    def to_row(self) -> dict:
        return {
            "policy": self.policy, "forecast": self.forecast,
            "total_g": round(self.total_g, 1), "exec_g": round(self.exec_g, 1),
            "migration_g": round(self.migration_g, 1), "resume_g": round(self.resume_g, 2),
            "migrations": self.migrations, "moves": self.moves, "waits": self.waits,
            "refuses": self.refuses, "deadline_violations": self.deadline_violations,
            "unfinished": self.unfinished, "sla_violation_slots": self.sla_violation_slots,
            "capacity_rejections": self.capacity_rejections,
            "mean_completion_h": round(self.mean_completion_h, 2),
        }


def run_simulation(
    traces: Dict[str, Sequence[float]],
    jobs: Sequence[Job],
    policy: Policy,
    cost_model,
    latency_ms: Optional[Dict[str, Dict[str, float]]] = None,
    capacity: Optional[Dict[str, float]] = None,
    slot_h: float = 1.0,
    forecast: Optional[ForecastProvider] = None,
    horizon_slots: int = 24,
    evaluation_horizon_h: float = 24.0,
    margin_g: float = 0.0,
    log_decisions: bool = False,
    resume_cost: bool = True,
    record_timeline: bool = False,
) -> SimResult:
    traces = {r: np.asarray(list(v), dtype=float) for r, v in traces.items()}
    regions = list(traces)
    T = min(len(v) for v in traces.values())
    forecast = forecast or OracleForecast(traces)
    jobs = [copy.deepcopy(j) for j in jobs]
    for j in jobs:
        if j.region not in regions:
            j.region = regions[0]
            j.origin = regions[0]

    exec_g = mig_g = res_g = 0.0
    counts = {a: 0 for a in ActionType}
    migrations = sla_slots = cap_rej = 0
    log: List[dict] = []
    timeline: List[dict] = []
    if record_timeline:
        log_decisions = True
    load: Dict[str, float] = {r: 0.0 for r in regions}

    for t in range(T):
        now_h = t * slot_h
        ci_now = {r: float(traces[r][t]) for r in regions}
        active = [j for j in jobs if not j.done and j.release_h <= now_h + 1e-9]
        applied_actions: Dict[str, str] = {}
        if not active:
            if record_timeline:
                timeline.append(_snapshot(t, now_h, jobs, applied_actions, exec_g, mig_g, res_g, migrations))
            continue
        ctx = SimContext(
            t=t, now_h=now_h, slot_h=slot_h, regions=regions, ci_now=ci_now,
            forecast=forecast, cost_model=cost_model, latency_ms=latency_ms,
            capacity=capacity, load=dict(load), horizon_slots=horizon_slots,
            evaluation_horizon_h=evaluation_horizon_h, margin_g=margin_g,
        )
        decisions = policy.decide_all(ctx, active)

        out = step_slot(active, decisions, ci_now, cost_model, regions, latency_ms, capacity, load,
                        slot_h, now_h, t, resume_cost, log_decisions)
        exec_g += out.exec_g
        mig_g += out.mig_g
        res_g += out.res_g
        migrations += out.migrations
        sla_slots += out.sla_slots
        cap_rej += out.cap_rej
        for act, n in out.counts.items():
            counts[act] += n
        applied_actions = out.applied
        log.extend(out.log)
        load = out.load
        if record_timeline:
            timeline.append(_snapshot(t, now_h, jobs, applied_actions, exec_g, mig_g, res_g, migrations))

    deadline_viol = unfinished = 0
    completions = []
    for j in jobs:
        if j.is_always_on:
            continue
        if not j.done:
            unfinished += 1
            if j.deadline_h is not None:
                deadline_viol += 1
        else:
            completions.append(j.completed_at_h - j.release_h)
            if j.deadline_h is not None and j.completed_at_h > j.deadline_h + 1e-9:
                deadline_viol += 1

    fc_name = getattr(policy.forecast_override or forecast, "name", "?")
    return SimResult(
        policy=policy.name, forecast=fc_name,
        total_g=exec_g + mig_g + res_g, exec_g=exec_g, migration_g=mig_g, resume_g=res_g,
        migrations=migrations, moves=counts[ActionType.MOVE], waits=counts[ActionType.WAIT],
        holds=counts[ActionType.HOLD], refuses=counts[ActionType.REFUSE],
        deadline_violations=deadline_viol, unfinished=unfinished,
        sla_violation_slots=sla_slots, capacity_rejections=cap_rej,
        mean_completion_h=float(np.mean(completions)) if completions else float("nan"),
        jobs=jobs, decisions=log, timeline=timeline,
    )


def _snapshot(t, now_h, jobs, applied_actions, exec_g, mig_g, res_g, migrations) -> dict:
    snap_jobs = {}
    for j in jobs:
        if j.done:
            status = "done"
        elif j.release_h > now_h + 1e-9:
            status = "not-released"
        elif j.running:
            status = "running"
        elif j.started:
            status = "suspended"
        else:
            status = "pending"
        snap_jobs[j.job_id] = {
            "region": j.region, "status": status, "action": applied_actions.get(j.job_id),
            "progress": round(min(1.0, j.progress_h / j.duration_h), 3) if j.duration_h > 0 else 1.0,
        }
    return {"t": t, "jobs": snap_jobs,
            "cum": {"exec_g": round(exec_g, 2), "migration_g": round(mig_g, 2), "resume_g": round(res_g, 3),
                    "total_g": round(exec_g + mig_g + res_g, 2), "migrations": migrations}}


def compare_policies(
    traces, jobs, policies: Sequence[Policy], cost_model, baseline: str = "carbon-unaware", **kw
) -> pd.DataFrame:
    results = [run_simulation(traces, jobs, p, cost_model, **kw) for p in policies]
    df = pd.DataFrame([r.to_row() for r in results])
    oracle_rows = df[df["policy"].str.startswith("oracle")]
    ref = float(oracle_rows["total_g"].min()) if len(oracle_rows) else float(df["total_g"].min())
    df["regret_g"] = (df["total_g"] - ref).round(1)
    if baseline in set(df["policy"]):
        base = float(df.loc[df["policy"] == baseline, "total_g"].iloc[0])
        df["reduction_vs_unaware_pct"] = ((1 - df["total_g"] / base) * 100).round(1)
    df.attrs["results"] = results
    return df
