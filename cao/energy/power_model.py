"""Utilisation-based power model: P(u) = P_idle + (P_max - P_idle) * u.

Placeholder until calibrated against a wall meter / RAPL. Linear CPU power models are
standard in the literature (Fan et al. 2007) but the constants are machine-specific.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass
class UtilizationPowerModel:
    idle_watts: float = 10.0
    max_watts: float = 45.0

    def power_w(self, utilisation: float) -> float:
        u = min(1.0, max(0.0, utilisation))
        return self.idle_watts + (self.max_watts - self.idle_watts) * u

    def energy_j(self, utilisations: Sequence[float], dt_s: float) -> float:
        return float(sum(self.power_w(u) for u in utilisations) * dt_s)

    @classmethod
    def from_config(cls, cfg: dict) -> "UtilizationPowerModel":
        return cls(float(cfg.get("idle_watts", 10.0)), float(cfg.get("max_watts", 45.0)))
