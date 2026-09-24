"""Carbon Payback Period (CPP).

    rate_r        = P_job [kW] * CI_r [g/kWh]                      -> g/h
    CPP           = MigrationCarbon / (rate_current - rate_destination)   -> hours
    MOVE iff remaining runtime > CPP  (equivalently: saved carbon > migration carbon)

Worked example from the plan: migration 500 g, current 600 g/h, destination 100 g/h
=> CPP = 500 / 500 = 1 h.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Union

Number = Union[int, float]


def carbon_rate_g_per_h(power_kw: float, ci_g_per_kwh: float) -> float:
    return power_kw * ci_g_per_kwh


def saved_carbon_g(
    power_kw: float,
    ci_src: Union[float, Sequence[float]],
    ci_dst: Union[float, Sequence[float]],
    hours: float,
    slot_h: float = 1.0,
) -> float:
    """Carbon avoided by running `hours` at destination instead of source.

    Scalars: constant CI.  Sequences: per-slot CI forecasts (first `hours/slot_h` slots
    are used, partial last slot pro-rated).  Negative result means destination is dirtier.
    """
    if isinstance(ci_src, (int, float)) and isinstance(ci_dst, (int, float)):
        return power_kw * (float(ci_src) - float(ci_dst)) * hours
    src = _as_list(ci_src)
    dst = _as_list(ci_dst)
    n = min(len(src), len(dst))
    total = 0.0
    left = hours
    for i in range(n):
        if left <= 1e-12:
            break
        h = min(slot_h, left)
        total += power_kw * (src[i] - dst[i]) * h
        left -= h
    if left > 1e-12 and n > 0:
        # forecast shorter than remaining runtime: extend with last known values
        total += power_kw * (src[n - 1] - dst[n - 1]) * left
    return total


def payback_hours(migration_g: float, rate_src_g_per_h: float, rate_dst_g_per_h: float) -> float:
    """Hours of remaining execution needed before a migration is carbon-neutral.

    Returns math.inf when the destination is not cleaner (never pays back).
    """
    delta = rate_src_g_per_h - rate_dst_g_per_h
    if delta <= 0:
        return math.inf
    if migration_g <= 0:
        return 0.0
    return migration_g / delta


def should_move(remaining_h: float, payback_h: float, margin_h: float = 0.0) -> bool:
    return remaining_h > payback_h + margin_h


@dataclass
class BoundaryPoint:
    state_gb: float
    migration_g: float
    payback_h: float          # minimum remaining runtime for MOVE


def payback_boundary(
    power_kw: float,
    ci_src: float,
    ci_dst: float,
    state_sizes_gb: Iterable[float],
    cost_model,
) -> List[BoundaryPoint]:
    """Carbon Payback Boundary: min remaining runtime for MOVE as a function of state size."""
    out: List[BoundaryPoint] = []
    rate_src = carbon_rate_g_per_h(power_kw, ci_src)
    rate_dst = carbon_rate_g_per_h(power_kw, ci_dst)
    for s in state_sizes_gb:
        mig = cost_model.carbon_g(s, ci_src, ci_dst).total_g
        out.append(BoundaryPoint(s, mig, payback_hours(mig, rate_src, rate_dst)))
    return out


def _as_list(x) -> List[float]:
    if isinstance(x, (int, float)):
        return [float(x)]
    return [float(v) for v in x]
