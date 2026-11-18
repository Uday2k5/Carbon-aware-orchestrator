"""Baseline and proposed scheduling policies.

    carbon-unaware        fixed placement, run ASAP                       (Baseline 1)
    greenest-region       always move to min-CI feasible region, cost=0   (Baseline 2)
    wait-only             never migrate; temporal shifting only           (Baseline 3)
    move-only             payback-aware migration, no delaying            (Baseline 4)
    migration-aware       payback + WAIT + SLA, greedy                    (proposed, heuristic)
    migration-aware-milp  joint MILP over the forecast horizon            (proposed)
    oracle-*              any of the above with perfect forecasts
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from ..core.models import ActionType, Decision, Job
from ..decision.engine import DecisionEngine
from ..decision.sla import feasible_regions
from ..decision.temporal import decide_temporal
from .forecast_providers import ForecastProvider, OracleForecast


@dataclass
class SimContext:
    t: int
    now_h: float
    slot_h: float
    regions: List[str]
    ci_now: Dict[str, float]
    forecast: ForecastProvider
    cost_model: object
    latency_ms: Optional[Dict[str, Dict[str, float]]] = None
    capacity: Optional[Dict[str, float]] = None
    load: Dict[str, float] = field(default_factory=dict)
    horizon_slots: int = 24
    evaluation_horizon_h: float = 24.0
    margin_g: float = 0.0
    forecast_upper: Optional[ForecastProvider] = None      # pessimistic (upper-band) forecast, when a model provides one

    def forecasts(self, provider: Optional[ForecastProvider] = None) -> Dict[str, np.ndarray]:
        return (provider or self.forecast).all(self.regions, self.t, self.horizon_slots)

    def upper(self) -> Optional[Dict[str, np.ndarray]]:
        return self.forecast_upper.all(self.regions, self.t, self.horizon_slots) if self.forecast_upper is not None else None


class Policy:
    name = "base"

    def __init__(self, forecast: Optional[ForecastProvider] = None, name: Optional[str] = None):
        self.forecast_override = forecast
        if name:
            self.name = name

    def _fc(self, ctx: SimContext) -> Dict[str, np.ndarray]:
        return ctx.forecasts(self.forecast_override)

    def _engine(self, ctx: SimContext, **kw) -> DecisionEngine:
        return DecisionEngine(
            ctx.cost_model, ctx.regions, ctx.latency_ms, ctx.capacity, ctx.slot_h,
            ctx.margin_g, ctx.evaluation_horizon_h, ctx.horizon_slots, **kw,
        )

    def decide_all(self, ctx: SimContext, jobs: Sequence[Job]) -> Dict[str, Decision]:
        raise NotImplementedError


class CarbonUnawarePolicy(Policy):
    name = "carbon-unaware"

    def decide_all(self, ctx, jobs):
        return {
            j.job_id: Decision(j.job_id, ActionType.HOLD, target_region=j.region,
                               reason="carbon-unaware: run in place", remaining_h=j.remaining_h)
            for j in jobs
        }


class GreenestRegionPolicy(Policy):
    name = "greenest-region"

    def decide_all(self, ctx, jobs):
        out = {}
        for j in jobs:
            A = [r for r in feasible_regions(j, ctx.regions, ctx.latency_ms) if r in ctx.ci_now]
            g = min(A, key=lambda r: ctx.ci_now[r]) if A else j.region
            if g != j.region and ctx.ci_now[g] < ctx.ci_now.get(j.region, float("inf")):
                out[j.job_id] = Decision(
                    j.job_id, ActionType.MOVE, target_region=g,
                    reason=f"greenest region ({ctx.ci_now[g]:.0f} g/kWh); migration cost ignored",
                    remaining_h=j.remaining_h,
                )
            else:
                out[j.job_id] = Decision(j.job_id, ActionType.HOLD, target_region=j.region,
                                         reason="already in greenest feasible region",
                                         remaining_h=j.remaining_h)
        return out


class WaitOnlyPolicy(Policy):
    name = "wait-only"

    def decide_all(self, ctx, jobs):
        fc = self._fc(ctx)
        out = {}
        for j in jobs:
            if not j.running and j.preemptible and not j.is_always_on and j.region in fc:
                out[j.job_id] = decide_temporal(j, fc[j.region], ctx.now_h, ctx.slot_h)
            else:
                out[j.job_id] = Decision(j.job_id, ActionType.HOLD, target_region=j.region,
                                         reason="wait-only: never migrates", remaining_h=j.remaining_h)
        return out


class MoveOnlyPolicy(Policy):
    name = "move-only"

    def decide_all(self, ctx, jobs):
        eng = self._engine(ctx, allow_wait=False)
        return eng.decide(jobs, self._fc(ctx), ctx.now_h, mode="heuristic")


class MigrationAwarePolicy(Policy):
    name = "migration-aware"

    def __init__(self, forecast=None, name=None, risk_aware: bool = False):
        super().__init__(forecast, name)
        self.risk_aware = risk_aware

    def decide_all(self, ctx, jobs):
        eng = self._engine(ctx, allow_wait=True, risk_aware=self.risk_aware)
        return eng.decide(jobs, self._fc(ctx), ctx.now_h, mode="heuristic", ci_upper=ctx.upper() if self.risk_aware else None)


class MilpPolicy(Policy):
    """Joint MILP plan over the horizon. `replan_every=k` re-solves every k slots and reads the
    intermediate slots off the stored plan (jobs released in between fall back to the greedy engine)."""

    name = "migration-aware-milp"

    def __init__(self, forecast=None, name=None, time_limit_s: float = 10.0, replan_every: int = 1):
        super().__init__(forecast, name)
        self.time_limit_s = time_limit_s
        self.replan_every = max(1, replan_every)
        self.solve_times: List[float] = []
        self.fallbacks = 0     # times the solver could not run and the greedy engine answered instead
        self._plan = None      # (t_solved, MilpResult, job_ids)

    def decide_all(self, ctx, jobs):
        eng = self._engine(ctx, allow_wait=True, milp_time_limit_s=self.time_limit_s)
        ids = {j.job_id for j in jobs}
        if self._plan is not None:
            t_solved, res, planned_ids = self._plan
            off = ctx.t - t_solved
            if 0 < off < self.replan_every and ids <= planned_ids and off < len(next(iter(res.plan.values()), [])):
                return self._from_plan(res, off, jobs, ctx)
        out = eng.decide(jobs, self._fc(ctx), ctx.now_h, mode="milp")
        res = eng.last_milp
        if getattr(res, "solve_time_s", None) is not None and getattr(res, "ok", False):
            self.solve_times.append(res.solve_time_s)
            self._plan = (ctx.t, res, ids)
        else:
            self.fallbacks += 1
        return out

    @staticmethod
    def _from_plan(res, off, jobs, ctx):
        out = {}
        for j in jobs:
            plan = res.plan[j.job_id]
            r = plan[off]
            if r is None:
                nxt = next((k for k in range(off, len(plan)) if plan[k]), None)
                resume = ctx.now_h + (nxt - off) * ctx.slot_h if nxt is not None else None
                out[j.job_id] = Decision(j.job_id, ActionType.WAIT, target_region=j.region,
                                         resume_at_h=resume, reason="MILP plan (cached)",
                                         remaining_h=j.remaining_h)
            elif r != j.region:
                out[j.job_id] = Decision(j.job_id, ActionType.MOVE, target_region=r,
                                         reason="MILP plan (cached)", remaining_h=j.remaining_h)
            else:
                out[j.job_id] = Decision(j.job_id, ActionType.HOLD, target_region=r,
                                         reason="MILP plan (cached)", remaining_h=j.remaining_h)
        return out


def oracle(policy: Policy, traces) -> Policy:
    """Same policy, perfect forecasts."""
    policy.forecast_override = OracleForecast(traces)
    policy.name = f"oracle-{policy.name}"
    return policy


def default_policies(traces=None, include_milp: bool = True, include_oracle: bool = True) -> List[Policy]:
    pols: List[Policy] = [
        CarbonUnawarePolicy(),
        GreenestRegionPolicy(),
        WaitOnlyPolicy(),
        MoveOnlyPolicy(),
        MigrationAwarePolicy(),
    ]
    if include_milp:
        pols.append(MilpPolicy())
    if include_oracle and traces is not None:
        pols.append(oracle(MilpPolicy() if include_milp else MigrationAwarePolicy(), traces))
    return pols
