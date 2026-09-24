"""Electricity Maps API (token in ELECTRICITY_MAPS_TOKEN). Only realistic option for India
zones (IN-WE, IN-NO, ...). Free tier: recent history (24 h) per call -> run `cao carbon
collect` on a schedule to build a dataset over weeks, or purchase historical access.
"""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import requests

from ..schema import normalize
from .base import CarbonSource

URL = "https://api.electricitymap.org/v3/carbon-intensity/history"


class ElectricityMapsSource(CarbonSource):
    name = "electricity-maps"

    def __init__(self, token: str = None, session: requests.Session = None, timeout: float = 30.0):
        self.token = token or os.environ.get("ELECTRICITY_MAPS_TOKEN")
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch(self, region: str, grid: str, start: datetime = None, end: datetime = None) -> pd.DataFrame:
        if not self.token:
            raise RuntimeError("ELECTRICITY_MAPS_TOKEN not set (see .env.example)")
        resp = self.session.get(URL, params={"zone": grid}, headers={"auth-token": self.token},
                                timeout=self.timeout)
        resp.raise_for_status()
        hist = resp.json().get("history", [])
        if not hist:
            raise RuntimeError("Electricity Maps returned no history")
        df = pd.DataFrame({"timestamp": [h["datetime"] for h in hist],
                           "ci_g_per_kwh": [h["carbonIntensity"] for h in hist]})
        out = normalize(df, region, self.name)
        if start is not None:
            out = out[out["timestamp"] >= pd.Timestamp(start, tz="UTC")]
        if end is not None:
            out = out[out["timestamp"] < pd.Timestamp(end, tz="UTC")]
        return out.reset_index(drop=True)
