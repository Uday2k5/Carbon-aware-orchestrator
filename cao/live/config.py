from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml

DEFAULT = Path(__file__).resolve().parents[2] / "config" / "live.yaml"


@dataclass
class LiveConfig:
    site: dict
    locations: List[dict]
    latency_ms: Dict[str, Dict[str, float]]
    services: List[dict]
    backfill_days: int = 60
    warm_start_hours: int = 72
    capacity_cpu: float = 16
    arrival_rate: float = 0.7
    max_active_jobs: int = 14
    raw: dict = field(default_factory=dict)

    @property
    def ids(self) -> List[str]:
        return [l["id"] for l in self.locations]

    def location(self, loc_id: str) -> dict:
        return next(l for l in self.locations if l["id"] == loc_id)


def load_live_config(path=None) -> LiveConfig:
    p = Path(path or os.environ.get("CAO_LIVE_CONFIG", DEFAULT))
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    ids = [l["id"] for l in raw["locations"]]
    same = float(raw.get("latency_same", 5))
    lat = {a: {b: (same if a == b else 999.0) for b in ids} for a in ids}
    for a, b, ms in raw.get("latency_pairs", []):
        if a in lat and b in lat:
            lat[a][b] = lat[b][a] = float(ms)
    return LiveConfig(
        site=raw.get("site", {}), locations=raw["locations"], latency_ms=lat,
        services=raw.get("services", []), backfill_days=int(raw.get("backfill_days", 60)),
        warm_start_hours=int(raw.get("warm_start_hours", 72)), capacity_cpu=float(raw.get("capacity_cpu", 16)),
        arrival_rate=float(raw.get("arrival_rate", 0.7)), max_active_jobs=int(raw.get("max_active_jobs", 14)),
        raw=raw,
    )


def load_dotenv(path=".env") -> None:
    """Tiny .env reader (KEY=VALUE per line); existing environment variables win."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        if k.strip() and v and k.strip() not in os.environ:
            os.environ[k.strip()] = v
