"""Hard latency (SLO) constraint.

    if RTT(user_region, compute_region) > SLA:  compute_region is prohibited
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from ..core.models import Job


def rtt_ms(latency_ms: Dict[str, Dict[str, float]], user_region: str, compute_region: str) -> float:
    try:
        return float(latency_ms[user_region][compute_region])
    except KeyError:
        return float("inf")


def feasible_regions(
    job: Job,
    regions: Iterable[str],
    latency_ms: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[str]:
    """Regions where `job` may run: SLA-feasible, and only the current one if immovable."""
    regions = list(regions)
    if not job.movable:
        return [job.region] if job.region in regions else regions[:1]
    if job.sla_rtt_ms is None or job.user_region is None or latency_ms is None:
        return regions
    return [r for r in regions if rtt_ms(latency_ms, job.user_region, r) <= job.sla_rtt_ms]
