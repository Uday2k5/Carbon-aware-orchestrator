"""SQLite telemetry store (stdlib only). Schema in docs/06-database-schema.md."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS carbon_intensity (
  timestamp TEXT NOT NULL, region TEXT NOT NULL, ci_g_per_kwh REAL NOT NULL, source TEXT,
  PRIMARY KEY (timestamp, region)
);
CREATE TABLE IF NOT EXISTS migration_measurements (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, state_gb REAL, bytes_state INTEGER,
  checkpoint_s REAL, checkpoint_j REAL, transfer_s REAL, transfer_j REAL, bytes_transferred INTEGER,
  restore_s REAL, restore_j REAL, transport TEXT, energy_method TEXT, repeat INTEGER
);
CREATE TABLE IF NOT EXISTS energy_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, job_id TEXT, region TEXT,
  joules REAL, seconds REAL, method TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, job_id TEXT, action TEXT,
  from_region TEXT, target_region TEXT, resume_at_h REAL, saved_g REAL, migration_g REAL,
  payback_h REAL, remaining_h REAL, reason TEXT, mode TEXT, applied INTEGER
);
CREATE TABLE IF NOT EXISTS migrations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, job_id TEXT, from_region TEXT,
  to_region TEXT, state_gb REAL, checkpoint_s REAL, reschedule_s REAL, total_s REAL,
  success INTEGER, detail TEXT
);
CREATE TABLE IF NOT EXISTS sim_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, experiment TEXT, policy TEXT, forecast TEXT,
  total_g REAL, exec_g REAL, migration_g REAL, migrations INTEGER, deadline_violations INTEGER,
  sla_violation_slots INTEGER, regret_g REAL, params TEXT
);
"""


class Database:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.environ.get("CAO_DB", "results/cao.sqlite")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------ carbon
    def upsert_carbon(self, df: pd.DataFrame) -> int:
        rows = [(pd.Timestamp(r.timestamp).isoformat(), r.region, float(r.ci_g_per_kwh), r.source)
                for r in df.itertuples(index=False)]
        with self.connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO carbon_intensity VALUES (?,?,?,?)", rows)
        return len(rows)

    def load_carbon(self, regions: Optional[Iterable[str]] = None) -> pd.DataFrame:
        q = "SELECT timestamp, region, ci_g_per_kwh, source FROM carbon_intensity"
        params: tuple = ()
        if regions:
            regions = list(regions)
            q += f" WHERE region IN ({','.join('?' * len(regions))})"
            params = tuple(regions)
        with self.connect() as con:
            df = pd.read_sql_query(q + " ORDER BY timestamp", con, params=params)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    # --------------------------------------------------------- generic
    def insert_df(self, table: str, df: pd.DataFrame) -> int:
        with self.connect() as con:
            cols = [c[1] for c in con.execute(f"PRAGMA table_info({table})")]
        keep = [c for c in df.columns if c in cols]
        with self.connect() as con:
            df[keep].to_sql(table, con, if_exists="append", index=False)
        return len(df)

    def insert_decision(self, decision, from_region: str, mode: str, applied: bool, timestamp: str) -> None:
        d = decision.to_dict()
        with self.connect() as con:
            con.execute(
                "INSERT INTO decisions (timestamp, job_id, action, from_region, target_region, resume_at_h,"
                " saved_g, migration_g, payback_h, remaining_h, reason, mode, applied)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (timestamp, d["job_id"], d["action"], from_region, d["target_region"], d["resume_at_h"],
                 d["saved_g"], d["migration_g"], d["payback_h"], d["remaining_h"], d["reason"], mode,
                 int(applied)),
            )

    def insert_migration(self, record: dict) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO migrations (timestamp, job_id, from_region, to_region, state_gb, checkpoint_s,"
                " reschedule_s, total_s, success, detail) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (record.get("timestamp"), record.get("job_id"), record.get("from_region"),
                 record.get("to_region"), record.get("state_gb"), record.get("checkpoint_s"),
                 record.get("reschedule_s"), record.get("total_s"), int(bool(record.get("success"))),
                 json.dumps(record.get("detail", {}))),
            )

    def table(self, name: str) -> pd.DataFrame:
        with self.connect() as con:
            return pd.read_sql_query(f"SELECT * FROM {name}", con)
