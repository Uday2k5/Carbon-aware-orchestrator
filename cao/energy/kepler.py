"""Kepler (Kubernetes-based Efficient Power Level Exporter) via Prometheus.

    joules = query_container_joules("http://localhost:9090", pod="ml-training-xyz", namespace="cao",
                                    start=..., end=...)

kepler_container_joules_total is a counter; we take increase() over the window.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import requests


def query_container_joules(
    prom_url: str, pod: str, namespace: str, start: datetime, end: datetime,
    session: Optional[requests.Session] = None, timeout: float = 30.0,
) -> float:
    window = int((end - start).total_seconds())
    q = (f'sum(increase(kepler_container_joules_total{{pod_name="{pod}",'
         f'container_namespace="{namespace}"}}[{window}s]))')
    s = session or requests.Session()
    resp = s.get(f"{prom_url.rstrip('/')}/api/v1/query",
                 params={"query": q, "time": end.timestamp()}, timeout=timeout)
    resp.raise_for_status()
    result = resp.json()["data"]["result"]
    if not result:
        return 0.0
    return float(result[0]["value"][1])
