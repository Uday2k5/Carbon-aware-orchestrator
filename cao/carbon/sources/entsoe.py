"""ENTSO-E Transparency Platform via entsoe-py (pip install entsoe-py; token in ENTSOE_TOKEN).

Generation per production type (A75) -> CI with IPCC lifecycle factors.
Covers Sweden (SE_3), France (FR) and every other ENTSO-E bidding zone.
"""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd

from ..emission_factors import ENTSOE_MAP, ci_from_mix
from ..schema import normalize
from .base import CarbonSource


class EntsoeSource(CarbonSource):
    name = "entsoe"

    def __init__(self, token: str = None):
        self.token = token or os.environ.get("ENTSOE_TOKEN")

    def fetch(self, region: str, grid: str, start: datetime, end: datetime) -> pd.DataFrame:
        if not self.token:
            raise RuntimeError("ENTSOE_TOKEN not set (see .env.example)")
        try:
            from entsoe import EntsoePandasClient
        except ImportError as exc:
            raise ImportError("pip install entsoe-py") from exc
        client = EntsoePandasClient(api_key=self.token)
        s = pd.Timestamp(start, tz="UTC") if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start)
        e = pd.Timestamp(end, tz="UTC") if pd.Timestamp(end).tzinfo is None else pd.Timestamp(end)
        gen = client.query_generation(grid, start=s, end=e, psr_type=None)
        return generation_to_ci(gen, region, self.name)


def generation_to_ci(gen: pd.DataFrame, region: str, source: str) -> pd.DataFrame:
    """entsoe-py generation frame (columns = PSR types, possibly MultiIndex with
    'Actual Aggregated'/'Actual Consumption') -> normalized CI frame."""
    g = gen.copy()
    if isinstance(g.columns, pd.MultiIndex):
        # keep aggregated generation, drop pumped-storage consumption
        g = g.xs("Actual Aggregated", axis=1, level=1, drop_level=True) if "Actual Aggregated" in g.columns.get_level_values(1) else g.droplevel(1, axis=1)
    g = g.apply(pd.to_numeric, errors="coerce").fillna(0.0).clip(lower=0.0)
    ci = g.apply(lambda row: ci_from_mix(row.to_dict(), ENTSOE_MAP), axis=1)
    df = pd.DataFrame({"timestamp": g.index, "ci_g_per_kwh": ci.values})
    return normalize(df, region, source)
