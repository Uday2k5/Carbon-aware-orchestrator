"""One local schema for every carbon-intensity source.

    timestamp (UTC, hourly) | region | ci_g_per_kwh | source
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

COLUMNS = ["timestamp", "region", "ci_g_per_kwh", "source"]


def normalize(df: pd.DataFrame, region: str, source: str, max_gap_h: int = 3) -> pd.DataFrame:
    """Resample to hourly UTC means, interpolate short gaps, tag region/source."""
    d = df.copy()
    ts = pd.to_datetime(d["timestamp"], utc=True)
    d = d.assign(timestamp=ts).set_index("timestamp").sort_index()
    s = pd.to_numeric(d["ci_g_per_kwh"], errors="coerce").resample("1h").mean()
    s = s.interpolate(limit=max_gap_h, limit_area="inside")
    out = s.dropna().reset_index()
    out["region"] = region
    out["source"] = source
    return out[COLUMNS]


def to_traces(
    df: pd.DataFrame,
    regions: Optional[Iterable[str]] = None,
    start: Optional[str] = None,
    hours: Optional[int] = None,
) -> Dict[str, np.ndarray]:
    """Aligned hourly arrays per region on the timestamps all regions share."""
    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    regions = list(regions) if regions is not None else sorted(d["region"].unique())
    d = d[d["region"].isin(regions)]
    wide = d.pivot_table(index="timestamp", columns="region", values="ci_g_per_kwh", aggfunc="mean")
    wide = wide.dropna(how="any").sort_index()
    if start is not None:
        wide = wide[wide.index >= pd.Timestamp(start, tz="UTC")]
    if hours is not None:
        wide = wide.iloc[:hours]
    if wide.empty:
        raise ValueError("no overlapping timestamps across the requested regions")
    traces = {r: wide[r].to_numpy(dtype=float) for r in regions if r in wide}
    traces["__index__"] = wide.index  # timestamps; drop with strip_index() before simulating
    return traces


def strip_index(traces: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    return {k: v for k, v in traces.items() if k != "__index__"}
