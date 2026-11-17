"""Flat-file store kept next to the published site (so GitHub Pages history is the database)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


class LiveStore:
    def __init__(self, data_dir) -> None:
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---- hourly carbon intensity: wide csv, index = hour (UTC), one column per location
    def load_ci(self) -> pd.DataFrame:
        p = self.dir / "ci_hourly.csv"
        if not p.exists():
            return pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
        df = pd.read_csv(p)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df.set_index("timestamp").sort_index().astype(float)

    def save_ci(self, wide: pd.DataFrame, keep_days: int = 400) -> None:
        if len(wide):
            wide = wide[wide.index >= wide.index.max() - pd.Timedelta(days=keep_days)]
        out = wide.round(1).copy()
        out.index = out.index.strftime("%Y-%m-%dT%H:%M:%SZ")
        out.index.name = "timestamp"
        out.to_csv(self.dir / "ci_hourly.csv")

    # ---- json helpers
    def load_json(self, name: str, default: Any = None) -> Any:
        p = self.dir / name
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def save_json(self, name: str, obj: Any, indent=None) -> None:
        tmp = self.dir / (name + ".tmp")
        tmp.write_text(json.dumps(obj, separators=(",", ":") if indent is None else None, indent=indent), encoding="utf-8")
        tmp.replace(self.dir / name)

    # ---- append-only csv logs
    def append_rows(self, name: str, rows: list, columns: list, keep_last: int = 20000) -> None:
        if not rows:
            return
        p = self.dir / name
        new = pd.DataFrame(rows, columns=columns)
        if p.exists():
            new = pd.concat([pd.read_csv(p), new], ignore_index=True)
        new.tail(keep_last).to_csv(p, index=False)

    def read_rows(self, name: str) -> pd.DataFrame:
        p = self.dir / name
        return pd.read_csv(p) if p.exists() else pd.DataFrame()
