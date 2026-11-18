"""Live carbon-intensity feeds. Each fetcher returns a DataFrame [timestamp (UTC), ci] at the
feed's native resolution for [start, end].

    gb-regional       National Grid ESO regional API, half-hourly, no key
    energidata        Energinet Energi Data Service (Denmark), 5-minute, no key
    rte-eco2mix       RTE eCO2mix via ODRE open data (France), 15-minute, no key
    electricity-maps  Electricity Maps (India zones), hourly, needs ELECTRICITY_MAPS_TOKEN
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Tuple

import pandas as pd
import requests

UTC = timezone.utc
GB = "https://api.carbonintensity.org.uk"
DK = "https://api.energidataservice.dk/dataset/CO2Emis"
EM = "https://api.electricitymap.org/v3/carbon-intensity"
JSON_HDR = {"Accept": "application/json", "User-Agent": "carbon-aware-orchestrator-live/0.1"}


class MissingKey(RuntimeError):
    """The feed needs an API key that is not configured."""


def _get(session: requests.Session, url: str, tries: int = 3, sleep=time.sleep, **kw) -> requests.Response:
    kw.setdefault("headers", JSON_HDR)
    kw.setdefault("timeout", 60)
    for i in range(tries):
        r = session.get(url, **kw)
        if r.status_code == 429 and i < tries - 1:
            m = re.search(r"(\d+)\s*second", r.text or "")
            wait = float(r.headers.get("Retry-After") or (m.group(1) if m else 20))
            sleep(min(wait + 1.0, 70.0))
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("unreachable")


def _frame(rows: List[Tuple[str, float]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["timestamp", "ci"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["ci"] = pd.to_numeric(df["ci"], errors="coerce")
    return df.dropna().drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def fetch_gb_regional(loc: dict, start: datetime, end: datetime, session: requests.Session) -> pd.DataFrame:
    rid, rows, cur = loc["region_id"], [], start
    while cur < end:
        nxt = min(cur + timedelta(days=13), end)
        url = f"{GB}/regional/intensity/{cur:%Y-%m-%dT%H:%MZ}/{nxt:%Y-%m-%dT%H:%MZ}/regionid/{rid}"
        for d in _get(session, url).json()["data"]["data"]:
            rows.append((d["from"], d["intensity"]["forecast"]))
        cur = nxt
    return _frame(rows)


def fetch_gb_forward(loc: dict, now: datetime, session: requests.Session) -> pd.DataFrame:
    """National Grid's own forward forecast for the next 24 h (for display and comparison)."""
    url = f"{GB}/regional/intensity/{now:%Y-%m-%dT%H:%MZ}/fw24h/regionid/{loc['region_id']}"
    return _frame([(d["from"], d["intensity"]["forecast"]) for d in _get(session, url).json()["data"]["data"]])


def fetch_energidata(loc: dict, start: datetime, end: datetime, session: requests.Session) -> pd.DataFrame:
    params = {"start": f"{start:%Y-%m-%dT%H:%M}", "end": f"{end + timedelta(minutes=5):%Y-%m-%dT%H:%M}",
              "filter": json.dumps({"PriceArea": [loc["area"]]}), "sort": "Minutes5UTC asc",
              "timezone": "UTC", "limit": 0}
    recs = _get(session, DK, params=params).json().get("records", [])
    return _frame([(r["Minutes5UTC"] + "Z", r["CO2Emission"]) for r in recs])


FR_HOSTS = ("https://odre.opendatasoft.com", "https://opendata.reseaux-energies.fr")
FR_PATH = "/api/explore/v2.1/catalog/datasets/eco2mix-national-tr"


def fetch_rte(loc: dict, start: datetime, end: datetime, session: requests.Session) -> pd.DataFrame:
    """Bulk export first (either host); if that yields nothing, page through the records API newest-first."""
    where = f"date_heure >= date'{start:%Y-%m-%dT%H:%M:%SZ}' and taux_co2 is not null"
    rows: list = []
    for host in FR_HOSTS:
        try:
            data = _get(session, host + FR_PATH + "/exports/json", timeout=120,
                        params={"select": "date_heure,taux_co2", "order_by": "date_heure", "where": where}).json()
            rows = [(d["date_heure"], d["taux_co2"]) for d in data if isinstance(d, dict) and d.get("taux_co2") is not None]
        except Exception:
            rows = []
        if rows:
            return _frame(rows)
    last_err = None
    for host in FR_HOSTS:
        try:
            for offset in range(0, 6000, 100):
                res = _get(session, host + FR_PATH + "/records",
                           params={"select": "date_heure,taux_co2", "where": where, "order_by": "date_heure desc",
                                   "limit": 100, "offset": offset}).json().get("results", [])
                rows += [(d["date_heure"], d["taux_co2"]) for d in res if d.get("taux_co2") is not None]
                if len(res) < 100:
                    break
        except Exception as exc:
            last_err = exc
        if rows:
            return _frame(rows)
    if last_err is not None:
        raise last_err
    return _frame(rows)


def fetch_electricity_maps(loc: dict, start: datetime, end: datetime, session: requests.Session) -> pd.DataFrame:
    token = os.environ.get(loc.get("needs_key", "ELECTRICITY_MAPS_TOKEN"))
    if not token:
        raise MissingKey(loc.get("needs_key", "ELECTRICITY_MAPS_TOKEN"))
    hdr = dict(JSON_HDR, **{"auth-token": token})
    hist = _get(session, f"{EM}/history", params={"zone": loc["zone"]}, headers=hdr).json().get("history", [])
    hist = [h for h in hist if h.get("carbonIntensity") is not None]
    rows = [(h["datetime"], h["carbonIntensity"]) for h in hist]
    try:
        last = _get(session, f"{EM}/latest", params={"zone": loc["zone"]}, headers=hdr).json()
        if last.get("carbonIntensity") is not None:
            rows.append((last["datetime"], last["carbonIntensity"]))
            hist.append(last)
    except Exception:
        pass
    df = _frame(rows)
    # The provider marks hours it could not measure and filled in by a method of its own.  Pass that on:
    # the dashboard must say so, and no model is trained or scored on estimated values.
    est = [h for h in hist if h.get("isEstimated")]
    if hist:
        methods = sorted({str(h.get("estimationMethod")) for h in est if h.get("estimationMethod")})
        df.attrs["quality"] = {"estimated_pct": round(100.0 * len(est) / len(hist), 1), "method": ", ".join(methods) or None, "provider": "Electricity Maps"}
    return df


SOURCES: Dict[str, Callable] = {
    "gb-regional": fetch_gb_regional,
    "energidata": fetch_energidata,
    "rte-eco2mix": fetch_rte,
    "electricity-maps": fetch_electricity_maps,
}
FORWARD: Dict[str, Callable] = {"gb-regional": fetch_gb_forward}


def to_hourly(native: pd.DataFrame, now: datetime) -> pd.Series:
    """Hourly means keyed by hour start; the hour still in progress is excluded."""
    if native.empty:
        return pd.Series(dtype=float)
    s = native.set_index("timestamp")["ci"].astype(float)
    hourly = s.groupby(s.index.floor("h")).mean()
    return hourly[hourly.index < pd.Timestamp(now).floor("h")]
