"""Migration cost model.

    E_migration(S) = E_checkpoint(S) + E_transfer(S) + E_restore(S)     [Joules, compute side]
    E_phase(S)     = a * S + b                                            [S in GB]
    E_network(S)   = S * kWh_per_GB                                       [internet path]

    Carbon_migration = kWh(ckpt) * CI_src + kWh(transfer) * CI_src
                     + kWh(network) * CI_net + kWh(restore) * CI_dst

`a` and `b` per phase are FITTED from measurements (cao profile -> cao fit); the YAML
values are placeholders so the pipeline runs before the profiler has been executed.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from ..core.units import joules_to_kwh

PHASES = ("checkpoint", "transfer", "restore")


@dataclass(frozen=True)
class LinearPhase:
    a: float  # Joules per GB
    b: float  # Joules fixed overhead

    def energy_j(self, state_gb: float) -> float:
        return max(0.0, self.a * state_gb + self.b)


@dataclass
class MigrationCarbon:
    state_gb: float
    checkpoint_g: float
    transfer_g: float
    network_g: float
    restore_g: float
    energy_j: float          # compute-side joules (excludes network path)
    network_kwh: float
    downtime_s: float

    @property
    def total_g(self) -> float:
        return self.checkpoint_g + self.transfer_g + self.network_g + self.restore_g

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_g"] = self.total_g
        return d


@dataclass
class MigrationCostModel:
    checkpoint: LinearPhase
    transfer: LinearPhase
    restore: LinearPhase
    network_kwh_per_gb: float = 0.06
    network_ci_attribution: str = "mean"   # mean | src | dst
    downtime_base_s: float = 3.0
    downtime_per_gb_s: float = 4.0
    source: str = "placeholder"
    fit_stats: Dict[str, dict] = field(default_factory=dict)

    # ------------------------------------------------------------------ energy
    def energy_breakdown_j(self, state_gb: float) -> Dict[str, float]:
        return {
            "checkpoint": self.checkpoint.energy_j(state_gb),
            "transfer": self.transfer.energy_j(state_gb),
            "restore": self.restore.energy_j(state_gb),
        }

    def energy_j(self, state_gb: float) -> float:
        return sum(self.energy_breakdown_j(state_gb).values())

    def network_kwh(self, state_gb: float) -> float:
        return max(0.0, state_gb) * self.network_kwh_per_gb

    def downtime_s(self, state_gb: float) -> float:
        return self.downtime_base_s + self.downtime_per_gb_s * max(0.0, state_gb)

    def departure_carbon_g(self, state_gb: float, ci_src: float) -> float:
        """Source-side share of a migration (checkpoint + transfer + its share of network)."""
        e = self.energy_breakdown_j(state_gb)
        share = {"src": 1.0, "dst": 0.0}.get(self.network_ci_attribution, 0.5)
        return (joules_to_kwh(e["checkpoint"] + e["transfer"]) + share * self.network_kwh(state_gb)) * ci_src

    def arrival_carbon_g(self, state_gb: float, ci_dst: float) -> float:
        """Destination-side share (restore + its share of network). departure + arrival == carbon_g().total_g"""
        e = self.energy_breakdown_j(state_gb)
        share = {"src": 0.0, "dst": 1.0}.get(self.network_ci_attribution, 0.5)
        return (joules_to_kwh(e["restore"]) + share * self.network_kwh(state_gb)) * ci_dst

    def resume_energy_j(self, state_gb: float) -> float:
        """Energy to pause+resume in place (checkpoint + restore, no network)."""
        return self.checkpoint.energy_j(state_gb) + self.restore.energy_j(state_gb)

    def resume_carbon_g(self, state_gb: float, ci: float) -> float:
        return joules_to_kwh(self.resume_energy_j(state_gb)) * ci

    # ------------------------------------------------------------------ carbon
    def carbon_g(self, state_gb: float, ci_src: float, ci_dst: float) -> MigrationCarbon:
        e = self.energy_breakdown_j(state_gb)
        if self.network_ci_attribution == "src":
            ci_net = ci_src
        elif self.network_ci_attribution == "dst":
            ci_net = ci_dst
        else:
            ci_net = 0.5 * (ci_src + ci_dst)
        net_kwh = self.network_kwh(state_gb)
        return MigrationCarbon(
            state_gb=state_gb,
            checkpoint_g=joules_to_kwh(e["checkpoint"]) * ci_src,
            transfer_g=joules_to_kwh(e["transfer"]) * ci_src,
            network_g=net_kwh * ci_net,
            restore_g=joules_to_kwh(e["restore"]) * ci_dst,
            energy_j=sum(e.values()),
            network_kwh=net_kwh,
            downtime_s=self.downtime_s(state_gb),
        )

    # ------------------------------------------------------------- persistence
    @classmethod
    def from_config(cls, migration_cfg: dict, network_cfg: Optional[dict] = None) -> "MigrationCostModel":
        network_cfg = network_cfg or {}
        return cls(
            checkpoint=LinearPhase(**migration_cfg["checkpoint"]),
            transfer=LinearPhase(**migration_cfg["transfer"]),
            restore=LinearPhase(**migration_cfg["restore"]),
            network_kwh_per_gb=float(network_cfg.get("energy_kwh_per_gb", 0.06)),
            network_ci_attribution=str(network_cfg.get("ci_attribution", "mean")),
            downtime_base_s=float(migration_cfg.get("downtime_base_s", 3.0)),
            downtime_per_gb_s=float(migration_cfg.get("downtime_per_gb_s", 4.0)),
            source=str(migration_cfg.get("source", "placeholder")),
        )

    def to_dict(self) -> dict:
        return {
            "checkpoint": asdict(self.checkpoint),
            "transfer": asdict(self.transfer),
            "restore": asdict(self.restore),
            "network_kwh_per_gb": self.network_kwh_per_gb,
            "network_ci_attribution": self.network_ci_attribution,
            "downtime_base_s": self.downtime_base_s,
            "downtime_per_gb_s": self.downtime_per_gb_s,
            "source": self.source,
            "fit_stats": self.fit_stats,
        }

    def to_json(self, path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def from_json(cls, path) -> "MigrationCostModel":
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return cls(
            checkpoint=LinearPhase(**d["checkpoint"]),
            transfer=LinearPhase(**d["transfer"]),
            restore=LinearPhase(**d["restore"]),
            network_kwh_per_gb=d.get("network_kwh_per_gb", 0.06),
            network_ci_attribution=d.get("network_ci_attribution", "mean"),
            downtime_base_s=d.get("downtime_base_s", 3.0),
            downtime_per_gb_s=d.get("downtime_per_gb_s", 4.0),
            source=d.get("source", "json"),
            fit_stats=d.get("fit_stats", {}),
        )

    # -------------------------------------------------------------------- fit
    @classmethod
    def fit(
        cls,
        measurements,
        network_kwh_per_gb: float = 0.06,
        network_ci_attribution: str = "mean",
    ) -> "MigrationCostModel":
        """Least-squares fit of E = a*S + b per phase from profiler output.

        `measurements` is a pandas DataFrame with columns
        state_gb, checkpoint_j, transfer_j, restore_j, checkpoint_s, transfer_s, restore_s.
        """
        s = np.asarray(measurements["state_gb"], dtype=float)
        if len(s) < 2:
            raise ValueError("need at least two state sizes to fit a line")
        phases = {}
        stats = {}
        warnings_ = []
        for name in PHASES:
            y = np.asarray(measurements[f"{name}_j"], dtype=float)
            a, b, r2 = _fit_line(s, y)
            if a < 0:  # energy cannot decrease with state size: fall back to mean J/GB
                a, b = float(np.sum(y) / np.sum(s)), 0.0
            phases[name] = LinearPhase(a=a, b=max(0.0, b))
            stats[name] = {"a_j_per_gb": a, "b_j": b, "r2": r2, "n": int(len(s))}
            if r2 < 0.9:
                warnings_.append(f"{name}: R2={r2:.2f} < 0.9 -> use larger/more state sizes and repeats")
        downtime = sum(np.asarray(measurements[f"{p}_s"], dtype=float) for p in PHASES)
        d_a, d_b, d_r2 = _fit_line(s, downtime)
        if d_a < 0:
            d_a, d_b = float(np.sum(downtime) / np.sum(s)), 0.0
        stats["downtime"] = {"per_gb_s": d_a, "base_s": d_b, "r2": d_r2}
        if warnings_:
            stats["warnings"] = warnings_
            import warnings as _w
            for msg in warnings_:
                _w.warn(msg, stacklevel=2)
        return cls(
            checkpoint=phases["checkpoint"],
            transfer=phases["transfer"],
            restore=phases["restore"],
            network_kwh_per_gb=network_kwh_per_gb,
            network_ci_attribution=network_ci_attribution,
            downtime_base_s=max(0.0, d_b),
            downtime_per_gb_s=max(0.0, d_a),
            source=f"measured:{len(s)} points",
            fit_stats=stats,
        )


def _fit_line(x: np.ndarray, y: np.ndarray):
    if np.allclose(x, x[0]):
        raise ValueError("state sizes must vary to fit a line")
    a, b = np.polyfit(x, y, 1)
    pred = a * x + b
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return float(a), float(b), r2
