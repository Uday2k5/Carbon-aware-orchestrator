"""One scheduling slot: apply decisions, then execute. Shared by the offline simulator and the
live twin so both charge carbon identically."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..core.models import ActionType, Decision, Job
from ..decision.sla import rtt_ms


@dataclass
class SlotOutcome:
    exec_g: float = 0.0
    mig_g: float = 0.0
    res_g: float = 0.0
    migrations: int = 0
    sla_slots: int = 0
    cap_rej: int = 0
    counts: Dict[ActionType, int] = field(default_factory=lambda: {a: 0 for a in ActionType})
    applied: Dict[str, str] = field(default_factory=dict)
    log: List[dict] = field(default_factory=list)
    load: Dict[str, float] = field(default_factory=dict)


def step_slot(
    active: Sequence[Job],
    decisions: Dict[str, Decision],
    ci_now: Dict[str, float],
    cost_model,
    regions: Sequence[str],
    latency_ms: Optional[Dict[str, Dict[str, float]]] = None,
    capacity: Optional[Dict[str, float]] = None,
    load: Optional[Dict[str, float]] = None,
    slot_h: float = 1.0,
    now_h: float = 0.0,
    t: int = 0,
    resume_cost: bool = True,
    log_decisions: bool = False,
) -> SlotOutcome:
    out = SlotOutcome()
    load = dict(load or {})
    downtime_h: Dict[str, float] = {}
    for j in active:
        d = decisions.get(j.job_id) or Decision(j.job_id, ActionType.HOLD, target_region=j.region)
        was_running = j.running
        region_before = j.region
        action = d.action

        if action == ActionType.WAIT and (j.is_always_on or (j.running and not j.preemptible)):
            action = ActionType.HOLD
        if action == ActionType.MOVE and (not d.target_region or d.target_region == j.region):
            action = ActionType.HOLD

        if action == ActionType.MOVE:
            tgt = d.target_region
            if capacity is not None and load.get(tgt, 0.0) + j.cpu > capacity.get(tgt, float("inf")) + 1e-9:
                out.cap_rej += 1
                action = ActionType.HOLD
            else:
                mc = cost_model.carbon_g(j.state_gb, ci_now[j.region], ci_now[tgt])
                j.migration_carbon_g += mc.total_g
                out.mig_g += mc.total_g
                out.migrations += 1
                j.migrations += 1
                downtime_h[j.job_id] = mc.downtime_s / 3600.0
                j.region = tgt
                j.running = True
                j.started = True

        if action == ActionType.WAIT:
            j.running = False
        elif action in (ActionType.HOLD, ActionType.REFUSE):
            j.running = True
            j.started = True

        if resume_cost and j.running and not was_running and action != ActionType.MOVE:
            rc = cost_model.resume_carbon_g(j.state_gb, ci_now[j.region])
            j.migration_carbon_g += rc
            out.res_g += rc

        out.counts[action] += 1
        out.applied[j.job_id] = action.value
        if log_decisions:
            row = d.to_dict()
            row.update({"t": t, "applied": action.value, "region_before": region_before,
                        "region_after": j.region})
            out.log.append(row)

    out.load = {r: 0.0 for r in regions}
    for j in active:
        if not j.running:
            continue
        eff = max(0.0, slot_h - downtime_h.get(j.job_id, 0.0))
        eff = min(eff, j.remaining_h)
        if eff <= 0 and not j.is_always_on:
            continue
        c = j.power_kw * eff * ci_now[j.region]
        j.exec_carbon_g += c
        out.exec_g += c
        j.progress_h += eff
        out.load[j.region] = out.load.get(j.region, 0.0) + j.cpu
        if j.sla_rtt_ms is not None and j.user_region is not None and latency_ms is not None:
            if rtt_ms(latency_ms, j.user_region, j.region) > j.sla_rtt_ms:
                out.sla_slots += 1
        if j.remaining_h <= 1e-9:
            j.done = True
            j.running = False
            j.completed_at_h = now_h + eff
    return out
