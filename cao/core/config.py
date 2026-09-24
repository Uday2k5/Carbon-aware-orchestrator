"""Load config/regions.yaml into plain objects."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "regions.yaml"


@dataclass
class Settings:
    regions: Dict[str, dict]
    latency_ms: Dict[str, Dict[str, float]]
    power_model: dict
    network: dict
    migration_model: dict
    scheduler: dict = field(default_factory=dict)

    @property
    def region_names(self) -> List[str]:
        return list(self.regions.keys())

    @property
    def capacity_cpu(self) -> Dict[str, float]:
        return {r: float(v.get("capacity_cpu", 1e9)) for r, v in self.regions.items()}


def load_settings(path: "str | os.PathLike | None" = None) -> Settings:
    p = Path(path or os.environ.get("CAO_CONFIG", DEFAULT_CONFIG))
    with open(p, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Settings(
        regions=raw["regions"],
        latency_ms=raw["latency_ms"],
        power_model=raw.get("power_model", {"idle_watts": 10.0, "max_watts": 45.0}),
        network=raw.get("network", {"energy_kwh_per_gb": 0.06, "ci_attribution": "mean"}),
        migration_model=raw.get("migration_model", {}),
        scheduler=raw.get("scheduler", {}),
    )
