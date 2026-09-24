"""Temporal shifting ("Let's Wait Awhile"): run now or WAIT for a cleaner window."""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from ..core.models import ActionType, Decision, Job


def best_contiguous_window(
    ci: Sequence[float], duration_slots: int, earliest: int = 0, latest_start: Optional[int] = None
) -> Tuple[int, float]:
    """Start slot minimising sum(ci[start:start+duration]) within [earliest, latest_start]."""
    n = len(ci)
    if duration_slots <= 0:
        return earliest, 0.0
    last = n - duration_slots if latest_start is None else min(latest_start, n - duration_slots)
    if last < earliest:
        # Forecast too short or deadline too tight: best effort = start as early as allowed.
        window = ci[earliest:earliest + duration_slots]
        return earliest, float(sum(window))
    best_s, best_v = earliest, math.inf
    cur = float(sum(ci[earliest:earliest + duration_slots]))
    for s in range(earliest, last + 1):
        if s > earliest:
            cur += ci[s + duration_slots - 1] - ci[s - 1]
        if cur < best_v - 1e-12:
            best_s, best_v = s, cur
    return best_s, best_v


def cheapest_slots(
    ci: Sequence[float], k: int, earliest: int = 0, latest_end: Optional[int] = None
) -> Tuple[List[int], float]:
    """k cheapest slots in [earliest, latest_end) for a preemptible job."""
    n = len(ci) if latest_end is None else min(latest_end, len(ci))
    idx = list(range(earliest, n))
    if k <= 0:
        return [], 0.0
    idx.sort(key=lambda t: ci[t])
    chosen = sorted(idx[:k])
    return chosen, float(sum(ci[t] for t in chosen))


def decide_temporal(
    job: Job,
    forecast_ci: Sequence[float],
    now_h: float,
    slot_h: float = 1.0,
    region: Optional[str] = None,
) -> Decision:
    """WAIT until the cheapest start (contiguous execution) or run now (HOLD).

    `forecast_ci[i]` is the predicted CI for slot i counted from `now_h` in `region`
    (defaults to the job's current residence).
    """
    region = region or job.region
    dur = job.remaining_slots(slot_h)
    if dur <= 0 or job.is_always_on or not job.preemptible:
        return Decision(job.job_id, ActionType.HOLD, target_region=region,
                        reason="not deferrable", remaining_h=job.remaining_h)
    earliest = max(0, int(math.ceil((job.release_h - now_h) / slot_h - 1e-9)))
    if job.deadline_h is None:
        latest_start = None
    else:
        latest_start = int(math.floor((job.deadline_h - now_h) / slot_h + 1e-9)) - dur
        if latest_start < earliest:
            return Decision(job.job_id, ActionType.HOLD, target_region=region,
                            reason="deadline tight: run now", remaining_h=job.remaining_h)
    start, total = best_contiguous_window(forecast_ci, dur, earliest, latest_start)
    now_total = float(sum(forecast_ci[earliest:earliest + dur]))
    if start <= earliest:
        return Decision(job.job_id, ActionType.HOLD, target_region=region,
                        reason="now is the cleanest feasible window", remaining_h=job.remaining_h)
    saved = job.power_kw * (now_total - total) * slot_h
    return Decision(
        job.job_id, ActionType.WAIT, target_region=region,
        resume_at_h=now_h + start * slot_h,
        reason=f"waiting {start * slot_h:.0f} h saves {saved:.1f} g vs running now",
        saved_g=saved, remaining_h=job.remaining_h,
    )
