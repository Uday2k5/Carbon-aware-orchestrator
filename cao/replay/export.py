"""Replay JSON: one compact export of a simulation that the HTML page and the GIF renderer read.

    {
      meta:       {hours, slot_h, regions, n_jobs, cost_model, network_kwh_per_gb, generated}
      timestamps: [str] | null
      ci:         {region: [g/kWh per hour]}
      jobs:       [{job_id, kind, power_kw, duration_h, state_gb, origin, release_h, deadline_h, user_region, sla_rtt_ms}]
      policies:   [{name, forecast, summary, status[t][k], region[t][k], action[t][k], progress[t][k],
                    cum[t]{exec_g, migration_g, resume_g, total_g, migrations}, events[]}]
      payback:    {power_kw, ci_src, ci_dst, sizes_gb, remaining_h, payback_h[], migration_g[]}
    }
    status codes 0 not-released, 1 pending, 2 running, 3 suspended, 4 done; action M/W/H/R or null;
    region is an index into meta.regions.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

from ..core.models import Job
from ..decision.payback import payback_boundary

STATUS = {"not-released": 0, "pending": 1, "running": 2, "suspended": 3, "done": 4}
ACTION = {"MOVE": "M", "WAIT": "W", "HOLD": "H", "REFUSE": "R"}
PAYBACK_SIZES = [0.1, 0.5, 1, 2, 5, 10, 20, 60]
PAYBACK_REMAINING = [0.25, 0.5, 1, 2, 4, 8, 12, 24]


def _event_detail(row: dict) -> str:
    a = row["applied"]
    if a == "WAIT":
        resume = row.get("resume_at_h")
        base = f"resume at h{resume:.0f}" if resume is not None else "deferred"
        return base + (f"; saves {row['saved_g']:.0f} g" if row.get("saved_g") else "")
    if a in ("MOVE", "REFUSE"):
        pb = row.get("payback_h")
        pb_txt = "∞" if pb is None or not np.isfinite(pb) else f"{pb:.2f} h"
        return (f"saves {row.get('saved_g', 0):.0f} g, migration {row.get('migration_g', 0):.1f} g, "
                f"payback {pb_txt}, remaining {row.get('remaining_h', 0):.1f} h")
    return row.get("reason", "")


def build_replay(
    traces: Dict[str, Sequence[float]],
    jobs: Sequence[Job],
    results: Iterable,
    cost_model=None,
    timestamps: Optional[Sequence] = None,
    slot_h: float = 1.0,
    power_kw: float = 0.2,
) -> dict:
    regions = list(traces)
    T = min(len(traces[r]) for r in regions)
    job_ids = [j.job_id for j in jobs]
    ridx = {r: i for i, r in enumerate(regions)}

    out = {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hours": T, "slot_h": slot_h, "regions": regions, "n_jobs": len(jobs),
            "cost_model": getattr(cost_model, "source", None),
            "network_kwh_per_gb": getattr(cost_model, "network_kwh_per_gb", None),
        },
        "timestamps": [str(ts)[:16] + " UTC" for ts in list(timestamps)[:T]] if timestamps is not None else None,
        "ci": {r: [round(float(v), 1) for v in list(traces[r])[:T]] for r in regions},
        "jobs": [{
            "job_id": j.job_id, "kind": j.kind, "power_kw": round(j.power_kw, 3),
            "duration_h": round(j.duration_h, 2), "state_gb": round(j.state_gb, 3), "origin": j.origin,
            "release_h": round(j.release_h, 2), "deadline_h": None if j.deadline_h is None else round(j.deadline_h, 2),
            "user_region": j.user_region, "sla_rtt_ms": j.sla_rtt_ms, "preemptible": j.preemptible,
        } for j in jobs],
        "policies": [],
        "payback": None,
    }

    for res in results:
        tl = res.timeline
        if not tl:
            raise ValueError(f"policy {res.policy!r} has no timeline; run with record_timeline=True")
        n = min(T, len(tl))
        status, region, action, progress, cum = [], [], [], [], []
        for t in range(n):
            snap = tl[t]["jobs"]
            status.append([STATUS[snap[j]["status"]] for j in job_ids])
            region.append([ridx.get(snap[j]["region"], -1) for j in job_ids])
            action.append([ACTION.get(snap[j]["action"]) for j in job_ids])
            progress.append([snap[j]["progress"] for j in job_ids])
            cum.append(tl[t]["cum"])
        events = []
        for row in res.decisions:
            if row["applied"] in ("MOVE", "WAIT", "REFUSE"):
                events.append({
                    "t": row["t"], "job": row["job_id"], "action": row["applied"],
                    "from": row.get("region_before"), "to": row.get("target_region"),
                    "saved_g": round(row.get("saved_g") or 0, 1), "migration_g": round(row.get("migration_g") or 0, 2),
                    "payback_h": None if row.get("payback_h") in (None, float("inf")) else round(row["payback_h"], 2),
                    "detail": _event_detail(row), "reason": row.get("reason", ""),
                })
        out["policies"].append({
            "name": res.policy, "forecast": res.forecast, "summary": res.to_row(),
            "status": status, "region": region, "action": action, "progress": progress,
            "cum": cum, "events": events,
        })

    if cost_model is not None:
        means = {r: float(np.mean(out["ci"][r])) for r in regions}
        src = max(means, key=means.get)
        dst = min(means, key=means.get)
        pts = payback_boundary(power_kw, means[src], means[dst], PAYBACK_SIZES, cost_model)
        out["payback"] = {
            "power_kw": power_kw, "ci_src": round(means[src]), "ci_dst": round(means[dst]),
            "src": src, "dst": dst, "sizes_gb": PAYBACK_SIZES, "remaining_h": PAYBACK_REMAINING,
            "payback_h": [None if not np.isfinite(p.payback_h) else round(p.payback_h, 2) for p in pts],
            "migration_g": [round(p.migration_g, 1) for p in pts],
        }
    return out


def export_replay(path, *args, **kwargs) -> Path:
    data = build_replay(*args, **kwargs)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))
    return path


def load_replay(path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
