"""Great Britain: https://api.carbonintensity.org.uk  (National Grid ESO, no API key).

Half-hourly national intensity; we take 'actual' when present else 'forecast'.
Max 14 days per request -> chunked.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from ..schema import normalize
from .base import CarbonSource

BASE = "https://api.carbonintensity.org.uk/intensity"


class UkCarbonIntensitySource(CarbonSource):
    name = "uk"

    def __init__(self, session: requests.Session = None, timeout: float = 30.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch(self, region: str, grid: str, start: datetime, end: datetime) -> pd.DataFrame:
        start = _utc(start)
        end = _utc(end)
        rows = []
        cur = start
        while cur < end:
            nxt = min(cur + timedelta(days=13), end)
            url = f"{BASE}/{cur.strftime('%Y-%m-%dT%H:%MZ')}/{nxt.strftime('%Y-%m-%dT%H:%MZ')}"
            resp = self.session.get(url, headers={"Accept": "application/json"}, timeout=self.timeout)
            resp.raise_for_status()
            for item in resp.json().get("data", []):
                val = item["intensity"].get("actual")
                if val is None:
                    val = item["intensity"].get("forecast")
                rows.append({"timestamp": item["from"], "ci_g_per_kwh": val})
            cur = nxt
        if not rows:
            raise RuntimeError("UK API returned no data")
        return normalize(pd.DataFrame(rows), region, self.name)


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
