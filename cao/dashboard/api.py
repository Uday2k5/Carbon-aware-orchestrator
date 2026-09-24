"""FastAPI backend (pip install fastapi uvicorn):  uvicorn cao.dashboard.api:app --reload

GET  /health
GET  /regions                      regions + latency matrix
GET  /payback?state_gb=&power_kw=&ci_src=&ci_dst=&remaining_h=
GET  /boundary?power_kw=&ci_src=&ci_dst=
GET  /decisions                    last decisions from the sqlite store
GET  /migrations                   measured migrations
GET  /carbon?region=               stored CI rows
"""
from __future__ import annotations

import os
from typing import Optional

try:
    from fastapi import FastAPI, Query
except ImportError as exc:  # pragma: no cover
    raise ImportError("pip install fastapi uvicorn") from exc

from ..core.config import load_settings
from ..core.models import Job
from ..db.store import Database
from ..decision.payback import payback_boundary
from ..decision.simple import decide_simple
from ..migration.cost_model import MigrationCostModel

app = FastAPI(title="Carbon-Aware Orchestrator", version="0.1.0")
settings = load_settings()
model_path = os.environ.get("CAO_MIGRATION_MODEL", "config/migration_model.json")
cost_model = (MigrationCostModel.from_json(model_path) if os.path.exists(model_path)
              else MigrationCostModel.from_config(settings.migration_model, settings.network))
db = Database()


@app.get("/health")
def health():
    return {"ok": True, "cost_model": cost_model.source}


@app.get("/regions")
def regions():
    return {"regions": settings.regions, "latency_ms": settings.latency_ms}


@app.get("/payback")
def payback(state_gb: float, power_kw: float, ci_src: float, ci_dst: float, remaining_h: float):
    job = Job("q", "batch-processing", power_kw, remaining_h, state_gb, "src", running=True, started=True)
    d = decide_simple(job, {"src": ci_src, "dst": ci_dst}, cost_model)
    out = d.to_dict()
    out["migration_breakdown"] = cost_model.carbon_g(state_gb, ci_src, ci_dst).to_dict()
    return out


@app.get("/boundary")
def boundary(power_kw: float, ci_src: float, ci_dst: float,
             sizes: str = Query("0.1,0.5,1,5,10,20,60")):
    pts = payback_boundary(power_kw, ci_src, ci_dst, [float(s) for s in sizes.split(",")], cost_model)
    return [p.__dict__ for p in pts]


@app.get("/decisions")
def decisions(limit: int = 200):
    return db.table("decisions").tail(limit).to_dict(orient="records")


@app.get("/migrations")
def migrations(limit: int = 200):
    return db.table("migrations").tail(limit).to_dict(orient="records")


@app.get("/carbon")
def carbon(region: Optional[str] = None, limit: int = 1000):
    df = db.load_carbon([region] if region else None).tail(limit)
    df["timestamp"] = df["timestamp"].astype(str)
    return df.to_dict(orient="records")
