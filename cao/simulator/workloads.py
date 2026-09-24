"""Synthetic job generator for the three workload classes in the plan."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np

from ..core.models import Job, JobKind

DEFAULT_MIX = {"ml-training": 0.4, "batch-processing": 0.4, "web-service": 0.2}


def generate_jobs(
    n: int,
    regions: Sequence[str],
    horizon_h: float,
    seed: int = 0,
    mix: Optional[Dict[str, float]] = None,
    user_regions: Optional[Sequence[str]] = None,
) -> List[Job]:
    rng = np.random.default_rng(seed)
    mix = mix or DEFAULT_MIX
    kinds = list(mix)
    probs = np.asarray([mix[k] for k in kinds], dtype=float)
    probs /= probs.sum()
    regions = list(regions)
    user_regions = list(user_regions or regions)
    jobs: List[Job] = []
    for i in range(n):
        kind = kinds[rng.choice(len(kinds), p=probs)]
        origin = regions[rng.integers(len(regions))]
        if kind == JobKind.ML_TRAINING.value:
            dur = float(rng.uniform(4, 12))
            release = float(rng.uniform(0, max(0.0, horizon_h * 0.5)))
            slack = float(rng.uniform(1.5, 4.0))
            jobs.append(Job(
                job_id=f"ml-{i:03d}", kind=kind,
                power_kw=float(rng.uniform(0.15, 0.35)), duration_h=dur,
                state_gb=float(np.exp(rng.uniform(np.log(0.5), np.log(20.0)))),
                origin=origin, release_h=release, deadline_h=release + dur * slack,
                preemptible=True, cpu=2.0,
            ))
        elif kind == JobKind.BATCH.value:
            dur = float(rng.uniform(1, 4))
            release = float(rng.uniform(0, max(0.0, horizon_h * 0.7)))
            slack = float(rng.uniform(2.0, 6.0))
            jobs.append(Job(
                job_id=f"batch-{i:03d}", kind=kind,
                power_kw=float(rng.uniform(0.05, 0.15)), duration_h=dur,
                state_gb=float(np.exp(rng.uniform(np.log(0.1), np.log(5.0)))),
                origin=origin, release_h=release, deadline_h=release + dur * slack,
                preemptible=True, cpu=1.0,
            ))
        else:
            user = user_regions[rng.integers(len(user_regions))]
            jobs.append(Job(
                job_id=f"web-{i:03d}", kind=kind,
                power_kw=float(rng.uniform(0.05, 0.10)), duration_h=float(horizon_h),
                state_gb=float(rng.uniform(0.05, 0.5)),
                origin=user, release_h=0.0, deadline_h=None,
                user_region=user, sla_rtt_ms=float(rng.choice([50.0, 80.0, 120.0])),
                preemptible=False, cpu=1.0,
            ))
    return jobs


def plan_examples() -> List[Job]:
    """Job A / Job B from the plan's 'most important experiment'."""
    return [
        Job("job-A", "ml-training", power_kw=0.2, duration_h=2.0, state_gb=0.2, origin="india",
            running=True, started=True),
        Job("job-B", "ml-training", power_kw=0.2, duration_h=0.5, state_gb=60.0, origin="india",
            running=True, started=True),
    ]
