"""US EIA Open Data v2: hourly generation by fuel type per balancing authority (e.g. PJM).

Docs: https://www.eia.gov/opendata/  (free key -> EIA_API_KEY)
Endpoint: /electricity/rto/fuel-type-data/data/
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd
import requests

from ..emission_factors import EIA_MAP, ci_from_mix
from ..schema import normalize
from .base import CarbonSource

URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"


class EiaSource(CarbonSource):
    name = "eia"

    def __init__(self, api_key: str = None, session: requests.Session = None, timeout: float = 60.0):
        self.api_key = api_key or os.environ.get("EIA_API_KEY")
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch(self, region: str, grid: str, start: datetime, end: datetime) -> pd.DataFrame:
        if not self.api_key:
            raise RuntimeError("EIA_API_KEY not set (see .env.example)")
        rows = []
        offset = 0
        while True:
            params = {
                "api_key": self.api_key,
                "frequency": "hourly",
                "data[0]": "value",
                "facets[respondent][]": grid,
                "start": _fmt(start),
                "end": _fmt(end),
                "sort[0][column]": "period",
                "sort[0][direction]": "asc",
                "offset": offset,
                "length": 5000,
            }
            resp = self.session.get(URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json().get("response", {}).get("data", [])
            rows.extend(data)
            if len(data) < 5000:
                break
            offset += 5000
        if not rows:
            raise RuntimeError("EIA returned no data")
        return fuel_rows_to_ci(rows, region, self.name)


def fuel_rows_to_ci(rows, region: str, source: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    wide = df.pivot_table(index="period", columns="fueltype", values="value", aggfunc="sum").fillna(0.0)
    ci = wide.apply(lambda row: ci_from_mix(row.to_dict(), EIA_MAP), axis=1)
    out = pd.DataFrame({"timestamp": pd.to_datetime(wide.index, utc=True), "ci_g_per_kwh": ci.values})
    return normalize(out, region, source)


def _fmt(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H")
