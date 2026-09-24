"""Aggregate metrics across seeds / traces."""
from __future__ import annotations

from typing import Sequence

import pandas as pd


def summarize(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    """Mean and std per policy over several compare_policies() runs (different seeds)."""
    df = pd.concat(frames, ignore_index=True)
    num = ["total_g", "exec_g", "migration_g", "migrations", "deadline_violations",
           "sla_violation_slots", "regret_g"]
    num = [c for c in num if c in df.columns]
    g = df.groupby("policy")[num]
    out = g.mean().add_suffix("_mean").join(g.std().add_suffix("_std"))
    out["runs"] = g.size()
    return out.sort_values("total_g_mean").reset_index()


def carbon_reduction_pct(df: pd.DataFrame, baseline: str = "carbon-unaware") -> pd.Series:
    base = float(df.loc[df["policy"] == baseline, "total_g"].iloc[0])
    return ((1 - df.set_index("policy")["total_g"] / base) * 100).round(1)
