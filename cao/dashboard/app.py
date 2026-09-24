"""Streamlit dashboard (pip install streamlit matplotlib):  streamlit run cao/dashboard/app.py

Tabs: Carbon intensity | Payback boundary | Policy comparison | Decisions log
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import streamlit as st

from cao.carbon import generate_dataset
from cao.core.config import load_settings
from cao.db.store import Database
from cao.decision.payback import payback_boundary
from cao.migration.cost_model import MigrationCostModel

st.set_page_config(page_title="Carbon-Aware Orchestrator", layout="wide")
settings = load_settings()
model_path = os.environ.get("CAO_MIGRATION_MODEL", "config/migration_model.json")
cost_model = (MigrationCostModel.from_json(model_path) if os.path.exists(model_path)
              else MigrationCostModel.from_config(settings.migration_model, settings.network))
db = Database()

st.title("Carbon-Aware Autonomous Workload Orchestrator")
st.caption(f"migration cost model: {cost_model.source} | network {cost_model.network_kwh_per_gb} kWh/GB")

tab_ci, tab_pb, tab_sim, tab_dec = st.tabs(["Carbon intensity", "Payback boundary",
                                            "Policy comparison", "Decisions"])

with tab_ci:
    df = db.load_carbon()
    if df.empty:
        st.info("No stored CI data; showing synthetic traces. Run `cao carbon fetch` / `cao carbon synth --store`.")
        df = generate_dataset(settings.region_names, days=7)
    wide = df.pivot_table(index="timestamp", columns="region", values="ci_g_per_kwh")
    st.line_chart(wide)
    st.dataframe(wide.describe().T[["mean", "min", "max"]].round(0))

with tab_pb:
    c1, c2, c3 = st.columns(3)
    power = c1.number_input("Job power (kW)", 0.01, 5.0, 0.2, 0.01)
    ci_src = c2.number_input("Current region CI (g/kWh)", 1.0, 1500.0, 650.0, 10.0)
    ci_dst = c3.number_input("Destination CI (g/kWh)", 1.0, 1500.0, 50.0, 10.0)
    sizes = np.logspace(-1, np.log10(100), 30)
    pts = payback_boundary(power, ci_src, ci_dst, sizes, cost_model)
    pb = pd.DataFrame([p.__dict__ for p in pts]).replace(np.inf, np.nan)
    st.subheader("Minimum remaining runtime for MOVE vs state size")
    st.line_chart(pb.set_index("state_gb")[["payback_h"]])
    st.dataframe(pb.round(2))

with tab_sim:
    p = "results/exp02_policy_comparison.csv"
    if os.path.exists(p):
        res = pd.read_csv(p)
        st.bar_chart(res.set_index("policy")[["exec_g", "migration_g"]])
        st.dataframe(res)
    else:
        st.info("Run `python experiments/exp02_policy_comparison.py` first.")

with tab_dec:
    dec = db.table("decisions")
    if dec.empty:
        st.info("No decisions logged yet (controller not run).")
    else:
        st.dataframe(dec.tail(500))
        st.bar_chart(dec["action"].value_counts())
