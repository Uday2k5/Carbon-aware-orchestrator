"""The simplest scheduler: MOVE if carbon saved > migration carbon, else REFUSE.

    def decide(job, current_region, candidate_region):
        saved_carbon     = estimate_saved_carbon(job)
        migration_carbon = estimate_migration_carbon(job)
        return "MOVE" if saved_carbon > migration_carbon else "REFUSE"

Forecast-aware variant: pass per-slot CI sequences instead of scalars.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Union

from ..core.models import ActionType, Decision, Job
from .payback import carbon_rate_g_per_h, payback_hours, saved_carbon_g

CI = Union[float, Sequence[float]]


@dataclass
class CandidateEval:
    region: str
    saved_g: float
    migration_g: float
    payback_h: float
    ci_dst_now: float

    @property
    def net_g(self) -> float:
        return self.saved_g - self.migration_g


def _now(ci: CI) -> float:
    if isinstance(ci, (int, float)):
        return float(ci)
    return float(ci[0])


def evaluate_candidate(
    job: Job,
    candidate: str,
    ci_src: CI,
    ci_dst: CI,
    cost_model,
    remaining_h: Optional[float] = None,
    slot_h: float = 1.0,
) -> CandidateEval:
    rem = job.remaining_h if remaining_h is None else remaining_h
    saved = saved_carbon_g(job.power_kw, ci_src, ci_dst, rem, slot_h)
    mig = cost_model.carbon_g(job.state_gb, _now(ci_src), _now(ci_dst)).total_g
    payback = payback_hours(
        mig,
        carbon_rate_g_per_h(job.power_kw, _now(ci_src)),
        carbon_rate_g_per_h(job.power_kw, _now(ci_dst)),
    )
    return CandidateEval(candidate, saved, mig, payback, _now(ci_dst))


def decide_simple(
    job: Job,
    ci_by_region: Dict[str, CI],
    cost_model,
    allowed_regions: Optional[Iterable[str]] = None,
    margin_g: float = 0.0,
    remaining_h: Optional[float] = None,
    slot_h: float = 1.0,
) -> Decision:
    """MOVE to the best net-saving region, REFUSE if none pays back, HOLD if none is greener."""
    current = job.region
    allowed = list(allowed_regions) if allowed_regions is not None else list(ci_by_region)
    ci_src = ci_by_region[current]
    rem = job.remaining_h if remaining_h is None else remaining_h

    greener = []
    for r in allowed:
        if r == current or r not in ci_by_region:
            continue
        ev = evaluate_candidate(job, r, ci_src, ci_by_region[r], cost_model, rem, slot_h)
        if ev.saved_g > 0:
            greener.append(ev)

    if not greener:
        return Decision(job.job_id, ActionType.HOLD, reason="no greener feasible region",
                        remaining_h=rem)

    best = max(greener, key=lambda e: e.net_g)
    if best.net_g > margin_g:
        return Decision(
            job.job_id, ActionType.MOVE, target_region=best.region,
            reason=f"saves {best.saved_g:.1f} g > migration {best.migration_g:.1f} g "
                   f"(payback {best.payback_h:.2f} h < remaining {rem:.2f} h)",
            saved_g=best.saved_g, migration_g=best.migration_g,
            payback_h=best.payback_h, remaining_h=rem,
        )
    return Decision(
        job.job_id, ActionType.REFUSE, target_region=best.region,
        reason=f"migration {best.migration_g:.1f} g >= saving {best.saved_g:.1f} g "
               f"(payback {best.payback_h:.2f} h > remaining {rem:.2f} h)",
        saved_g=best.saved_g, migration_g=best.migration_g,
        payback_h=best.payback_h, remaining_h=rem,
    )
