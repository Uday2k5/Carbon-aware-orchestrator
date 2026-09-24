"""Migration-cost-aware MILP over a forecast horizon (PuLP + bundled CBC).

Sets      J jobs, R regions, T slots (hourly by default)
Variables x[j,r,t] in {0,1}   job j executes in region r during slot t
          l[j,r,t] in {0,1}   job j's *state resides* in region r during slot t
          dep[j,r,t], arr[j,r,t] in [0,1]   state left / arrived at r between t-1 and t
          q[j,r,t] in [0,1]   start or resume in r not explained by an arrival (pause cost)
          u[j] >= 0           unmet execution slots (soft deadline, heavily penalised)
Objective min  sum x * P_j * dt * CI[r,t]                              execution carbon
             + sum dep * C_departure(S_j, CI[r,t]) + arr * C_arrival(S_j, CI[r,t])
                   (one move = one departure + one arrival = full C_mig(src, dst))
             + sum q * kWh(E_ckpt + E_restore) * CI[r,t]
             + lambda_deadline * sum u[j]  + eps * sum (t+1) x
Constraints sum_r l[j,r,t] = 1            state lives in exactly one region
            x[j,r,t] <= l[j,r,t]          run only where the state is
            sum_{r,t} x + u[j] = remaining_slots_j
            x = 0 outside [release, deadline) and in SLA-infeasible regions
            dep[j,r,t] >= l[j,r,t-1] - l[j,r,t];  arr[j,r,t] >= l[j,r,t] - l[j,r,t-1]
            (t = release uses the current residence as the constant l[.,.,t-1])
            always-on services: sum_r x[j,r,t] = 1 for all t
            non-preemptible jobs: single contiguous execution block
            sum_j cpu_j x[j,r,t] <= capacity_r
Assumption: pausing a preemptible job is free (as in "Let's Wait Awhile"); moving it is not.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import pulp

from ..core.models import ActionType, Decision, Job
from .simple import evaluate_candidate
from .sla import feasible_regions


@dataclass
class MilpResult:
    status: str
    objective_g: float
    plan: Dict[str, List[Optional[str]]]     # job -> region executing in slot t (None = idle)
    residence: Dict[str, List[str]]          # job -> region holding the state in slot t
    unmet_slots: Dict[str, float]
    exec_g: float
    migration_g: float
    solve_time_s: float
    resume_g: float = 0.0
    build_time_s: float = 0.0
    n_variables: int = 0
    n_constraints: int = 0

    @property
    def ok(self) -> bool:
        return self.status in ("Optimal", "Not Solved") and bool(self.plan)


def solve_milp(
    jobs: Sequence[Job],
    regions: Sequence[str],
    ci: Dict[str, Sequence[float]],
    cost_model,
    latency_ms: Optional[Dict[str, Dict[str, float]]] = None,
    capacity: Optional[Dict[str, float]] = None,
    slot_h: float = 1.0,
    now_h: float = 0.0,
    horizon: Optional[int] = None,
    deadline_penalty_g: float = 1e4,
    time_limit_s: float = 20.0,
    msg: bool = False,
    time_pref_g: float = 1e-3,
    resume_cost: bool = True,
    gap_rel: Optional[float] = 0.005,
    threads: Optional[int] = None,
) -> MilpResult:
    """Solve the placement MILP.

    Variables exist only inside each job's active window [release, deadline) - moving state
    before release or after the deadline can never help, so residence is fixed outside it.
    `time_pref_g` is a tiny per-slot penalty that breaks ties towards finishing early;
    `resume_cost` charges checkpoint+restore energy whenever a job starts or resumes without
    an accompanying migration (so pausing is not free).
    """
    regions = [r for r in regions if r in ci]
    T = min(len(ci[r]) for r in regions)
    if horizon is not None:
        T = min(T, horizon)
    if T <= 0:
        raise ValueError("empty forecast horizon")

    t_build = time.perf_counter()
    prob = pulp.LpProblem("carbon_aware_placement", pulp.LpMinimize)
    x: Dict[tuple, pulp.LpVariable] = {}
    l: Dict[tuple, pulp.LpVariable] = {}
    u: Dict[str, pulp.LpVariable] = {}
    exec_terms, mig_terms, pen_terms, resume_terms, eps_terms = [], [], [], [], []
    allowed: Dict[str, List[str]] = {}
    windows: Dict[str, range] = {}
    rem_slots: Dict[str, int] = {}

    for j in jobs:
        jid = j.job_id
        A = feasible_regions(j, regions, latency_ms) or ([j.region] if j.region in regions else regions[:1])
        allowed[jid] = A
        rem = T if j.is_always_on else min(j.remaining_slots(slot_h), T)
        rem_slots[jid] = rem
        e = 0 if j.is_always_on else max(0, int(math.ceil((j.release_h - now_h) / slot_h - 1e-9)))
        if j.deadline_h is None or j.is_always_on:
            d = T
        else:
            d = min(T, int(math.floor((j.deadline_h - now_h) / slot_h + 1e-9)))
        win = range(e, d) if d > e else range(0)
        windows[jid] = win
        if len(win) == 0:
            continue  # nothing can run inside the horizon: all slots unmet (penalised below)
        cur = j.region

        for t in win:
            for r in A:
                l[jid, r, t] = pulp.LpVariable(f"l_{_s(jid)}_{_s(r)}_{t}", cat="Binary")
                v = pulp.LpVariable(f"x_{_s(jid)}_{_s(r)}_{t}", cat="Binary")
                x[jid, r, t] = v
                prob += v <= l[jid, r, t], f"where_{_s(jid)}_{_s(r)}_{t}"
                exec_terms.append(v * (j.power_kw * slot_h * float(ci[r][t])))
                eps_terms.append(v * (time_pref_g * (t + 1)))
            prob += pulp.lpSum(l[jid, r, t] for r in A) == 1, f"res_{_s(jid)}_{t}"
            if j.is_always_on:
                prob += pulp.lpSum(x[jid, r, t] for r in A) == 1, f"on_{_s(jid)}_{t}"

        u[jid] = pulp.LpVariable(f"u_{_s(jid)}", lowBound=0, upBound=rem)
        prob += (
            pulp.lpSum(x[jid, r, t] for t in win for r in A) + u[jid] == rem,
            f"work_{_s(jid)}",
        )
        pen_terms.append(deadline_penalty_g * u[jid])

        # state movement as departure / arrival indicators (2|R| vars per slot, exact cost split)
        arrivals: Dict[tuple, pulp.LpVariable] = {}
        e0 = win[0]
        if cur not in A and cur in ci:
            # current residence is not allowed: the state must leave it at the first slot
            mig_terms.append(cost_model.departure_carbon_g(j.state_gb, float(ci[cur][e0])))
        for t in win:
            for r in A:
                l_prev = (1 if cur == r else 0) if t == e0 else l[jid, r, t - 1]
                dep = pulp.LpVariable(f"dep_{_s(jid)}_{_s(r)}_{t}", lowBound=0, upBound=1)
                arr = pulp.LpVariable(f"arr_{_s(jid)}_{_s(r)}_{t}", lowBound=0, upBound=1)
                prob += dep >= l_prev - l[jid, r, t], f"dep_{_s(jid)}_{_s(r)}_{t}"
                prob += arr >= l[jid, r, t] - l_prev, f"arr_{_s(jid)}_{_s(r)}_{t}"
                mig_terms.append(dep * cost_model.departure_carbon_g(j.state_gb, float(ci[r][t])))
                mig_terms.append(arr * cost_model.arrival_carbon_g(j.state_gb, float(ci[r][t])))
                arrivals[r, t] = arr

        # start/resume cost: a rise of x in region r that no incoming migration explains
        running_now = j.running and e0 == 0
        if resume_cost:
            for t in win:
                for r in A:
                    if t == e0:
                        prev = 1 if (running_now and cur == r) else 0
                    else:
                        prev = x[jid, r, t - 1]
                    q = pulp.LpVariable(f"q_{_s(jid)}_{_s(r)}_{t}", lowBound=0, upBound=1)
                    prob += (
                        q >= x[jid, r, t] - prev - arrivals[r, t],
                        f"resume_{_s(jid)}_{_s(r)}_{t}",
                    )
                    resume_terms.append(q * cost_model.resume_carbon_g(j.state_gb, float(ci[r][t])))

        # contiguity for non-preemptible, not-always-on jobs
        if not j.preemptible and not j.is_always_on:
            a_prev = 1 if running_now else 0
            starts = []
            for t in win:
                a_t = pulp.lpSum(x[jid, r, t] for r in A)
                a_tm1 = a_prev if t == e0 else pulp.lpSum(x[jid, r, t - 1] for r in A)
                sv = pulp.LpVariable(f"s_{_s(jid)}_{t}", lowBound=0, upBound=1)
                prob += sv >= a_t - a_tm1, f"start_{_s(jid)}_{t}"
                starts.append(sv)
            prob += pulp.lpSum(starts) <= (0 if a_prev else 1), f"single_start_{_s(jid)}"

    if capacity:
        for r in regions:
            cap = float(capacity.get(r, math.inf))
            if math.isinf(cap):
                continue
            for t in range(T):
                terms = [j.cpu * x[j.job_id, r, t] for j in jobs if (j.job_id, r, t) in x]
                if terms:
                    prob += pulp.lpSum(terms) <= cap, f"cap_{_s(r)}_{t}"

    prob += (
        pulp.lpSum(exec_terms) + pulp.lpSum(mig_terms) + pulp.lpSum(resume_terms)
        + pulp.lpSum(pen_terms) + pulp.lpSum(eps_terms)
    )

    build_time = time.perf_counter() - t_build
    t0 = time.perf_counter()
    opts = {"msg": msg, "timeLimit": time_limit_s}
    if gap_rel is not None:
        opts["gapRel"] = gap_rel
    if threads:
        opts["threads"] = threads
    solver = pulp.PULP_CBC_CMD(**opts)
    if exec_terms or pen_terms:
        prob.solve(solver)
        status = pulp.LpStatus[prob.status]
    else:
        status = "Optimal"
    solve_time = time.perf_counter() - t0

    plan: Dict[str, List[Optional[str]]] = {}
    residence: Dict[str, List[str]] = {}
    unmet: Dict[str, float] = {}
    for j in jobs:
        jid = j.job_id
        A = allowed[jid]
        win = windows[jid]
        plan[jid] = [None] * T
        res_list: List[str] = [j.region] * T
        last_res = j.region
        for t in range(T):
            if t in win:
                for r in A:
                    if (x[jid, r, t].value() or 0) > 0.5:
                        plan[jid][t] = r
                        break
                last_res = max(A, key=lambda r: (l[jid, r, t].value() or 0))
            res_list[t] = last_res
        residence[jid] = res_list
        unmet[jid] = float(u[jid].value() or 0.0) if jid in u else float(rem_slots[jid])

    exec_g = float(pulp.value(pulp.lpSum(exec_terms)) or 0.0) if exec_terms else 0.0
    mig_g = float(pulp.value(pulp.lpSum(mig_terms)) or 0.0) if mig_terms else 0.0
    res_g = float(pulp.value(pulp.lpSum(resume_terms)) or 0.0) if resume_terms else 0.0
    return MilpResult(
        status=status,
        objective_g=float(pulp.value(prob.objective) or 0.0) if exec_terms else 0.0,
        plan=plan,
        residence=residence,
        unmet_slots=unmet,
        exec_g=exec_g,
        migration_g=mig_g,
        solve_time_s=solve_time,
        resume_g=res_g,
        build_time_s=build_time,
        n_variables=len(prob.variables()),
        n_constraints=len(prob.constraints),
    )


def plan_to_decisions(
    result: MilpResult,
    jobs: Sequence[Job],
    ci: Dict[str, Sequence[float]],
    cost_model,
    regions: Sequence[str],
    latency_ms=None,
    now_h: float = 0.0,
    slot_h: float = 1.0,
    evaluation_horizon_h: float = 24.0,
) -> Dict[str, Decision]:
    """Translate the first slot of the plan into MOVE / WAIT / HOLD / REFUSE per job."""
    out: Dict[str, Decision] = {}
    for j in jobs:
        plan = result.plan.get(j.job_id, [])
        rem_h = min(j.remaining_h, evaluation_horizon_h) if j.is_always_on else j.remaining_h
        run0 = plan[0] if plan else None
        A = feasible_regions(j, regions, latency_ms)
        if run0 is None:
            nxt = next((t for t, r in enumerate(plan) if r), None)
            if nxt is None:
                out[j.job_id] = Decision(
                    j.job_id, ActionType.WAIT, target_region=j.region,
                    resume_at_h=now_h + len(plan) * slot_h,
                    reason="MILP: no execution slot inside horizon (deadline window empty)",
                    remaining_h=rem_h,
                )
            else:
                out[j.job_id] = Decision(
                    j.job_id, ActionType.WAIT, target_region=plan[nxt],
                    resume_at_h=now_h + nxt * slot_h,
                    reason=f"MILP: cleaner window starts in {nxt * slot_h:.0f} h in {plan[nxt]}",
                    remaining_h=rem_h,
                )
        elif run0 != j.region:
            ev = evaluate_candidate(j, run0, ci[j.region], ci[run0], cost_model, rem_h, slot_h)
            out[j.job_id] = Decision(
                j.job_id, ActionType.MOVE, target_region=run0,
                reason=f"MILP plan: run in {run0} (payback {ev.payback_h:.2f} h, remaining {rem_h:.2f} h)",
                saved_g=ev.saved_g, migration_g=ev.migration_g, payback_h=ev.payback_h,
                remaining_h=rem_h,
            )
        else:
            greener = [r for r in A if r != j.region and float(ci[r][0]) < float(ci[j.region][0])]
            if greener:
                g = min(greener, key=lambda r: float(ci[r][0]))
                ev = evaluate_candidate(j, g, ci[j.region], ci[g], cost_model, rem_h, slot_h)
                out[j.job_id] = Decision(
                    j.job_id, ActionType.REFUSE, target_region=g,
                    reason=f"MILP keeps {j.region}: moving to {g} costs {ev.migration_g:.1f} g "
                           f"vs {ev.saved_g:.1f} g saved (payback {ev.payback_h:.2f} h)",
                    saved_g=ev.saved_g, migration_g=ev.migration_g, payback_h=ev.payback_h,
                    remaining_h=rem_h,
                )
            else:
                out[j.job_id] = Decision(
                    j.job_id, ActionType.HOLD, target_region=j.region,
                    reason="MILP: current placement optimal, no greener feasible region",
                    remaining_h=rem_h,
                )
    return out


def _s(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(name))
