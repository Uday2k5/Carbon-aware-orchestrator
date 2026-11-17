"""Hourly scheduling twin: simulated workloads, real grid data, real decisions.

Every policy sees the same job arrivals and is charged the same true carbon through the
simulator's step function. State is a plain dict so it can live in a JSON file between runs.
"""
from __future__ import annotations

import copy
import zlib
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..core.models import ActionType, Job
from ..simulator.forecast_providers import ForecastProvider
from ..simulator.policies import (CarbonUnawarePolicy, GreenestRegionPolicy, MigrationAwarePolicy, MilpPolicy,
                                  SimContext)
from ..simulator.step import step_slot

POLICIES = [
    ("ours", "Payback-aware (ours)", lambda: MigrationAwarePolicy()),
    ("ours-milp", "Payback-aware · 24 h MILP plan", lambda: MilpPolicy(time_limit_s=8)),
    ("greenest", "Always greenest region", lambda: GreenestRegionPolicy()),
    ("unaware", "Carbon-unaware", lambda: CarbonUnawarePolicy()),
]
FEED_POLICY = "ours"
COUNTERS = ("exec_g", "mig_g", "res_g", "migrations", "moves", "waits", "refuses", "holds", "done",
            "deadline_missed", "sla_slots", "cap_rej", "solver_fallbacks")
ISO = "%Y-%m-%dT%H:%M:%SZ"


class DictForecast(ForecastProvider):
    name = "live"

    def __init__(self, fc: Dict[str, np.ndarray]):
        self.fc = fc

    def forecast(self, region: str, t: int, horizon: int) -> np.ndarray:
        arr = np.asarray(self.fc[region], dtype=float)
        if len(arr) < horizon:
            arr = np.concatenate([arr, np.full(horizon - len(arr), arr[-1])])
        return arr[:horizon]

    def all(self, regions, t: int, horizon: int) -> Dict[str, np.ndarray]:
        return {r: self.forecast(r, t, horizon) for r in self.fc}   # includes stale regions jobs may sit in


class LiveTwin:
    def __init__(self, cfg, cost_model, state: dict):
        self.cfg = cfg
        self.cm = cost_model
        self.epoch = pd.Timestamp(state["epoch"])
        self.last_hour: Optional[pd.Timestamp] = pd.Timestamp(state["last_hour"]) if state.get("last_hour") else None
        self.series: List[list] = state.get("series", [])
        self.last_action: Dict[str, str] = state.get("last_action", {})
        self.services_created: List[str] = state.get("services_created", [])
        self.decisions_total: int = state.get("decisions_total", 0)
        self.jobs_created: int = state.get("jobs_created", 0)
        self.pol: Dict[str, dict] = {}
        for pid, _, _ in POLICIES:
            p = state.get("policies", {}).get(pid, {})
            self.pol[pid] = {k: p.get(k, 0) for k in COUNTERS}
            self.pol[pid]["jobs"] = [Job(**j) for j in p.get("jobs", [])]
            self.pol[pid]["load"] = p.get("load", {})

    @classmethod
    def new(cls, cfg, cost_model, epoch: pd.Timestamp) -> "LiveTwin":
        return cls(cfg, cost_model, {"epoch": epoch.strftime(ISO)})

    def to_state(self) -> dict:
        pols = {}
        for pid, P in self.pol.items():
            pols[pid] = {k: P[k] for k in COUNTERS}
            pols[pid]["jobs"] = [j.to_dict() for j in P["jobs"]]
            pols[pid]["load"] = P["load"]
        return {"epoch": self.epoch.strftime(ISO), "last_hour": self.last_hour.strftime(ISO) if self.last_hour is not None else None,
                "series": self.series, "last_action": self.last_action, "services_created": self.services_created,
                "decisions_total": self.decisions_total, "jobs_created": self.jobs_created, "policies": pols}

    # ------------------------------------------------------------------ arrivals
    def _add(self, job: Job) -> None:
        self.jobs_created += 1
        for P in self.pol.values():
            P["jobs"].append(copy.deepcopy(job))

    def _spawn(self, hour: pd.Timestamp, now_h: float, enabled: List[str]) -> None:
        for s in self.cfg.services:
            if s["id"] not in self.services_created and s["user"] in enabled:
                self.services_created.append(s["id"])
                self._add(Job(job_id=s["id"], kind="web-service", power_kw=float(s.get("power_kw", 0.08)), duration_h=1e6,
                              state_gb=float(s.get("state_gb", 0.2)), origin=s["user"], release_h=now_h,
                              user_region=s["user"], sla_rtt_ms=float(s["sla_ms"]), preemptible=False, cpu=1.0))
        active = sum(1 for j in self.pol[FEED_POLICY]["jobs"] if not j.is_always_on)
        if active >= self.cfg.max_active_jobs or not enabled:
            return
        rng = np.random.default_rng(zlib.crc32(f"arrivals|{hour.strftime(ISO)}".encode()))
        locs = sorted(enabled)
        for i in range(min(int(rng.poisson(self.cfg.arrival_rate)), 3)):
            origin = locs[int(rng.integers(len(locs)))]
            u = rng.random()
            if u < 0.40:        # ML training: long, moderate state
                dur = float(rng.uniform(4, 12))
                job = Job(job_id=f"ml-{hour:%m%d%H}{chr(97 + i)}", kind="ml-training", power_kw=round(float(rng.uniform(0.15, 0.35)), 3),
                          duration_h=round(dur, 2), state_gb=round(float(np.exp(rng.uniform(np.log(0.5), np.log(20.0)))), 2),
                          origin=origin, release_h=now_h, deadline_h=round(now_h + dur * float(rng.uniform(1.5, 4.0)), 2), cpu=2.0)
            elif u < 0.75:      # batch: short, light state
                dur = float(rng.uniform(1, 4))
                job = Job(job_id=f"bt-{hour:%m%d%H}{chr(97 + i)}", kind="batch-processing", power_kw=round(float(rng.uniform(0.05, 0.15)), 3),
                          duration_h=round(dur, 2), state_gb=round(float(np.exp(rng.uniform(np.log(0.1), np.log(5.0)))), 2),
                          origin=origin, release_h=now_h, deadline_h=round(now_h + dur * float(rng.uniform(2.0, 6.0)), 2), cpu=1.0)
            else:               # data pipeline: short, heavy state (the case where moving rarely pays back)
                dur = float(rng.uniform(0.5, 3))
                job = Job(job_id=f"dp-{hour:%m%d%H}{chr(97 + i)}", kind="data-pipeline", power_kw=round(float(rng.uniform(0.10, 0.25)), 3),
                          duration_h=round(dur, 2), state_gb=round(float(np.exp(rng.uniform(np.log(20.0), np.log(120.0)))), 1),
                          origin=origin, release_h=now_h, deadline_h=round(now_h + dur * float(rng.uniform(2.0, 5.0)), 2), cpu=1.0)
            self._add(job)

    # -------------------------------------------------------------------- advance
    def advance(self, hour: pd.Timestamp, ci_now: Dict[str, float], forecasts: Dict[str, np.ndarray],
                enabled: List[str]) -> List[dict]:
        """Process one completed hour. Returns new decision-feed rows (MOVE / WAIT / REFUSE of our policy)."""
        now_h = (hour - self.epoch) / pd.Timedelta(hours=1)
        self._spawn(hour, now_h, enabled)
        cap = {r: self.cfg.capacity_cpu for r in ci_now}
        feed: List[dict] = []
        for pid, _, make in POLICIES:
            P = self.pol[pid]
            active = [j for j in P["jobs"] if not j.done and j.release_h <= now_h + 1e-9 and j.region in ci_now]
            if active:
                ctx = SimContext(t=0, now_h=now_h, slot_h=1.0, regions=list(enabled), ci_now=ci_now,
                                 forecast=DictForecast(forecasts), cost_model=self.cm, latency_ms=self.cfg.latency_ms,
                                 capacity=cap, load=dict(P["load"]), horizon_slots=24, evaluation_horizon_h=24.0)
                policy = make()
                try:
                    decisions = policy.decide_all(ctx, active)
                except Exception:
                    decisions = {}
                P["solver_fallbacks"] += getattr(policy, "fallbacks", 0)
                out = step_slot(active, decisions, ci_now, self.cm, list(ci_now), self.cfg.latency_ms, cap, P["load"],
                                1.0, now_h, 0, True, log_decisions=(pid == FEED_POLICY))
                P["exec_g"] += out.exec_g
                P["mig_g"] += out.mig_g
                P["res_g"] += out.res_g
                P["migrations"] += out.migrations
                P["moves"] += out.counts[ActionType.MOVE]
                P["waits"] += out.counts[ActionType.WAIT]
                P["refuses"] += out.counts[ActionType.REFUSE]
                P["holds"] += out.counts[ActionType.HOLD]
                P["sla_slots"] += out.sla_slots
                P["cap_rej"] += out.cap_rej
                P["load"] = out.load
                if pid == FEED_POLICY:
                    self.decisions_total += len(active)
                    by_id = {j.job_id: j for j in active}
                    feed.extend(self._feed_rows(hour, out.log, by_id))
            for j in P["jobs"]:
                if j.done:
                    P["done"] += 1
                    if j.deadline_h is not None and (j.completed_at_h or 0) > j.deadline_h + 1e-9:
                        P["deadline_missed"] += 1
            P["jobs"] = [j for j in P["jobs"] if not j.done]
        alive = {j.job_id for j in self.pol[FEED_POLICY]["jobs"]}
        self.last_action = {k: v for k, v in self.last_action.items() if k in alive}
        self.series.append([hour.strftime(ISO)] + [round(self.total(pid), 1) for pid, _, _ in POLICIES])
        self.last_hour = hour
        return feed

    def _feed_rows(self, hour: pd.Timestamp, log: List[dict], by_id: Dict[str, Job]) -> List[dict]:
        rows = []
        for r in log:
            act, jid = r["applied"], r["job_id"]
            key = f"{act}|{r.get('target_region')}"
            prev = self.last_action.get(jid)
            self.last_action[jid] = key if act != "HOLD" else "HOLD"
            if act == "HOLD" or (act in ("WAIT", "REFUSE") and prev == key):
                continue
            if act == "REFUSE" and float(r.get("saved_g") or 0) < 1.0:
                continue        # a marginally greener grid that saves under a gram is not worth a feed line
            j = by_id[jid]
            pb = r.get("payback_h")
            resume = r.get("resume_at_h")
            rows.append({
                "ts": hour.strftime(ISO), "job": jid, "kind": j.kind, "state_gb": j.state_gb, "action": act,
                "from": r.get("region_before"), "to": r.get("target_region"),
                "saved_g": round(float(r.get("saved_g") or 0), 1), "migration_g": round(float(r.get("migration_g") or 0), 2),
                "payback_h": None if pb is None or not np.isfinite(pb) else round(float(pb), 2),
                "remaining_h": round(float(r.get("remaining_h") or 0), 2),
                "resume_at": (self.epoch + pd.Timedelta(hours=float(resume))).strftime(ISO) if resume is not None else None,
                "reason": r.get("reason", ""),
            })
        return rows

    # -------------------------------------------------------------------- summary
    def total(self, pid: str) -> float:
        P = self.pol[pid]
        return P["exec_g"] + P["mig_g"] + P["res_g"]

    def summary(self) -> dict:
        now_h = ((self.last_hour - self.epoch) / pd.Timedelta(hours=1)) if self.last_hour is not None else 0.0
        pols = []
        for pid, label, _ in POLICIES:
            P = self.pol[pid]
            pols.append({"id": pid, "label": label, "total_g": round(self.total(pid), 1), "exec_g": round(P["exec_g"], 1),
                         "migration_g": round(P["mig_g"] + P["res_g"], 1), "migrations": P["migrations"], "refuses": P["refuses"],
                         "waits": P["waits"], "done": P["done"], "deadline_missed": P["deadline_missed"],
                         "sla_violation_hours": P["sla_slots"], "active": len(P["jobs"]),
                         "solver_fallbacks": P["solver_fallbacks"]})
        jobs = []
        for j in self.pol[FEED_POLICY]["jobs"]:
            status = "running" if j.running else ("suspended" if j.started else "pending")
            jobs.append({"job_id": j.job_id, "kind": j.kind, "region": j.region, "origin": j.origin, "status": status,
                         "state_gb": j.state_gb, "power_kw": j.power_kw,
                         "progress": None if j.is_always_on else round(min(1.0, j.progress_h / j.duration_h), 3),
                         "remaining_h": None if j.is_always_on else round(j.remaining_h, 2),
                         "deadline_in_h": None if j.deadline_h is None else round(j.deadline_h - now_h - 1, 1),
                         "sla_ms": j.sla_rtt_ms, "user": j.user_region, "migrations": j.migrations,
                         "carbon_g": round(j.total_carbon_g, 1), "last": self.last_action.get(j.job_id)})
        return {"epoch": self.epoch.strftime(ISO), "last_hour": self.last_hour.strftime(ISO) if self.last_hour is not None else None,
                "hours": len(self.series), "policies": pols, "jobs": jobs, "series_columns": [pid for pid, _, _ in POLICIES],
                "series": self.series, "decisions_total": self.decisions_total, "jobs_created": self.jobs_created}
