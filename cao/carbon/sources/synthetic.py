"""Synthetic but realistic CI traces for offline development and unit tests.

Shape per region: base level + diurnal cycle (solar dip at midday, evening peak) + weekly
cycle + AR(1) weather noise.  Parameters roughly match 2023 public averages.  NEVER report
results on synthetic traces as findings; they exist so the pipeline runs without API keys.
"""
from __future__ import annotations

import zlib
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

from ..schema import COLUMNS
from .base import CarbonSource

# base, diurnal amplitude, weekly amplitude, AR(1) sigma, AR(1) phi, floor
PARAMS: Dict[str, dict] = {
    "india":   dict(base=680.0, diurnal=60.0, weekly=15.0, sigma=12.0, phi=0.85, floor=450.0),
    "sweden":  dict(base=38.0, diurnal=6.0, weekly=3.0, sigma=4.0, phi=0.9, floor=8.0),
    "france":  dict(base=58.0, diurnal=15.0, weekly=6.0, sigma=8.0, phi=0.9, floor=15.0),
    "us-east": dict(base=390.0, diurnal=45.0, weekly=20.0, sigma=15.0, phi=0.85, floor=250.0),
    "uk":      dict(base=190.0, diurnal=40.0, weekly=15.0, sigma=18.0, phi=0.92, floor=25.0),
}
DEFAULT = dict(base=300.0, diurnal=40.0, weekly=10.0, sigma=15.0, phi=0.85, floor=20.0)


def generate_trace(region: str, hours: int, seed: int = 0, start_hour: int = 0) -> np.ndarray:
    p = PARAMS.get(region, DEFAULT)
    rng = np.random.default_rng(zlib.crc32(f"{region}|{seed}".encode()))  # stable across processes
    t = np.arange(hours) + start_hour
    hour = t % 24
    diurnal = p["diurnal"] * (np.cos(2 * np.pi * (hour - 19) / 24)          # evening peak
                              - 0.6 * np.exp(-((hour - 13) ** 2) / 8.0))    # midday solar dip
    weekly = p["weekly"] * np.cos(2 * np.pi * (t / 24 - 1) / 7)             # weekend lower
    noise = np.zeros(hours)
    for i in range(1, hours):
        noise[i] = p["phi"] * noise[i - 1] + rng.normal(0, p["sigma"])
    ci = p["base"] + diurnal + weekly + noise
    return np.maximum(ci, p["floor"])


def generate_dataset(regions: Iterable[str], days: int = 30, seed: int = 0,
                     start: Optional[datetime] = None) -> pd.DataFrame:
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    hours = days * 24
    idx = pd.date_range(start, periods=hours, freq="1h", tz="UTC")
    frames = []
    for r in regions:
        frames.append(pd.DataFrame({
            "timestamp": idx, "region": r,
            "ci_g_per_kwh": generate_trace(r, hours, seed, start.hour), "source": "synthetic",
        }))
    return pd.concat(frames, ignore_index=True)[COLUMNS]


class SyntheticSource(CarbonSource):
    name = "synthetic"

    def __init__(self, seed: int = 0):
        self.seed = seed

    def fetch(self, region: str, grid: str, start: datetime, end: datetime) -> pd.DataFrame:
        hours = int((end - start).total_seconds() // 3600)
        return generate_dataset([region], days=max(1, hours // 24), seed=self.seed, start=start)
