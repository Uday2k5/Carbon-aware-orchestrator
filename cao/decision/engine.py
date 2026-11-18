"""Decision engine: combines SLA filtering, temporal shifting, payback test and (optionally) MILP.

    heuristic mode (default):  per-job, greedy, forecast-aware, explainable
    milp mode:                 joint plan over the horizon, decoded into the same actions
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

from ..core.models import ActionType, Decision, Job
from .milp import plan_to_decisions, solve_milp
from .simple import decide_simple
from .sla import feasible_regions
from .temporal import best_contiguous_window


class DecisionEngine:
    def __init__(
        self,
        cost_model,
        regions: Sequence[str],
        latency_ms: Optional[Dict[str, Dict[str, float]]] = None,
        capacity: Optional[Dict[str, float]] = None,
        slot_h: float = 1.0,
        margin_g: float = 0.0,
        evaluation_horizon_h: float = 24.0,
        horizon_slots: int = 24,
        deadline_penalty_g: float = 1e4,
        milp_time_limit_s: float = 20.0,
        allow_wait: bool = True,
        allow_move: bool = True,
        risk_aware: bool = False,
    ) -> None:
        self.cost_model = cost_model
        self.regions = list(regions)
        self.latency_ms = latency_ms
        self.capacity = capacity
        self.slot_h = slot_h
        self.margin_g = margin_g
        self.evaluation_horizon_h = evaluation_horizon_h
        self.horizon_slots = horizon_slots
        self.deadline_penalty_g = deadline_penalty_g
        self.milp_time_limit_s = milp_time_limit_s
        self.allow_wait = allow_wait
        self.allow_move = allow_move
        self.risk_aware = risk_aware     # WAIT only if the later window beats running now even at the pessimistic forecast
        self.ci_upper: Optional[Dict[str, Sequence[float]]] = None
        self.last_milp = None

    # ------------------------------------------------------------------ public
    def decide(
        self,
        jobs: Sequence[Job],
        ci_forecast: Dict[str, Sequence[float]],
        now_h: float = 0.0,
        mode: str = "heuristic",
        ci_upper: Optional[Dict[str, Sequence[float]]] = None,
    ) -> Dict[str, Decision]:
        self.ci_upper = ci_upper
        jobs = [j for j in jobs if not j.done]
        if mode == "milp" and jobs:
            try:
                res = solve_milp(
                    jobs, self.regions, ci_forecast, self.cost_model, self.latency_ms,
                    self.capacity, self.slot_h, now_h, self.horizon_slots,
                    self.deadline_penalty_g, self.milp_time_limit_s,
                )
                self.last_milp = res
                if res.ok:
                    return plan_to_decisions(
                        res, jobs, ci_forecast, self.cost_model, self.regions, self.latency_ms,
                        now_h, self.slot_h, self.evaluation_horizon_h,
                    )
            except Exception as exc:  # solver missing / numerical trouble -> degrade gracefully
                self.last_milp = exc
        return {j.job_id: self.decide_one(j, ci_forecast, now_h) for j in jobs}

    def decide_one(self, job: Job, ci: Dict[str, Sequence[float]], now_h: float = 0.0) -> Decision:
        if job.region not in ci:
            return Decision(job.job_id, ActionType.HOLD, reason=f"no CI data for {job.region}")
        A = feasible_regions(job, self.regions, self.latency_ms)
        A = [r for r in A if r in ci]
        if not self.allow_move:
            A = [job.region]
        rem_h = min(job.remaining_h, self.evaluation_horizon_h) if job.is_always_on else job.remaining_h
        if rem_h <= 0:
            return Decision(job.job_id, ActionType.HOLD, reason="nothing left to run")

        deferrable = (
            self.allow_wait and job.preemptible and not job.is_always_on and not job.running
        )
        if deferrable:
            d = self._decide_pending(job, ci, A, now_h)
            if d is not None:
                return d
        return decide_simple(
            job, ci, self.cost_model, allowed_regions=A, margin_g=self.margin_g,
            remaining_h=rem_h, slot_h=self.slot_h,
        )

    # ----------------------------------------------------------------- private
    def _decide_pending(self, job: Job, ci, A, now_h: float) -> Optional[Decision]:
        """Joint choice of (region, start slot) for a job that is not running right now."""
        dur = job.remaining_slots(self.slot_h)
        n = min(len(ci[r]) for r in A)
        earliest = max(0, int(math.ceil((job.release_h - now_h) / self.slot_h - 1e-9)))
        if job.deadline_h is None:
            latest_start = n - dur
        else:
            latest_start = int(math.floor((job.deadline_h - now_h) / self.slot_h + 1e-9)) - dur
        if latest_start < earliest:
            return None  # deadline tight: fall back to "start now, best region"

        best, now_best = None, None
        for r in A:
            start, tot = best_contiguous_window(ci[r], dur, earliest, latest_start)
            exec_g = job.power_kw * tot * self.slot_h
            if r == job.region:
                mig = 0.0
            else:
                mig = self.cost_model.carbon_g(
                    job.state_gb, float(ci[job.region][start]), float(ci[r][start])
                ).total_g
            total = exec_g + mig
            if best is None or total < best[0] - 1e-9:
                best = (total, r, start, exec_g, mig)
            now_g = job.power_kw * float(sum(ci[r][earliest:earliest + dur])) * self.slot_h
            if r != job.region:
                now_g += self.cost_model.carbon_g(job.state_gb, float(ci[job.region][earliest]), float(ci[r][earliest])).total_g
            if now_best is None or now_g < now_best[0] - 1e-9:
                now_best = (now_g, r)
        if best is None:
            return None
        total, r, start, exec_g, mig = best
        if self.risk_aware and self.ci_upper is not None and start > earliest and r in self.ci_upper:
            up = self.ci_upper[r]
            pess = job.power_kw * float(sum(up[start:start + dur])) * self.slot_h + mig
            if pess >= now_best[0]:          # the later window is not reliably cleaner: do not gamble, start now
                if now_best[1] != job.region:
                    return None              # start now elsewhere -> payback test decides and explains it
                return Decision(job.job_id, ActionType.HOLD, target_region=job.region,
                                reason="a cleaner window is forecast, but not reliably enough to wait for",
                                remaining_h=job.remaining_h)
        baseline = job.power_kw * float(sum(ci[job.region][earliest:earliest + dur])) * self.slot_h
        saved = baseline - total
        if start > earliest:
            return Decision(
                job.job_id, ActionType.WAIT, target_region=r,
                resume_at_h=now_h + start * self.slot_h,
                reason=f"cleaner window in {r} starts in {start * self.slot_h:.0f} h "
                       f"(saves {saved:.1f} g vs running now here)",
                saved_g=saved, migration_g=mig, remaining_h=job.remaining_h,
            )
        if r != job.region:
            return None  # start now elsewhere -> let the payback test explain it
        return Decision(
            job.job_id, ActionType.HOLD, target_region=r,
            reason="now is the cleanest feasible window here",
            remaining_h=job.remaining_h,
        )
