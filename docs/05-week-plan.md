# 12-week plan (3 students, ~350 person-hours)

Critical path: **profiler → fitted cost model → payback boundary → simulator baselines → MILP → k8s demo**.

| week | Member 1 (infra) | Member 2 (forecast) | Member 3 (sim / eval) | milestone |
| --- | --- | --- | --- | --- |
| 1 | WSL2, Docker, k3d cluster, node labels | API keys; UK + ENTSO-E fetch working | run tests, read simulator, EXP-01 with placeholders | repo runs on all 3 machines |
| 2 | `cao profile` on real sizes 0.1–20 GB, ×3 repeats | EIA + Electricity Maps; 60+ days per region | payback boundary plots; job generator tuned | **fitted `migration_model.json`** |
| 3 | wall-meter calibration of power model | features + persistence / seasonal baselines | EXP-02 on synthetic; verify accounting | first H2 figure |
| 4 | workload images; checkpoint-on-SIGTERM verified | gradient boosting + XGBoost, backtest MAE/MAPE | EXP-02 on real traces | H1 preliminary |
| 5 | controller dry-run against cluster | uncertainty (residual intervals) | MILP vs greedy comparison, solve times | mid-term review |
| 6 | controller applies MOVE; downtime measured | `ModelForecast` provider into simulator | EXP-03 forecast sensitivity | **end-to-end demo v1** |
| 7 | 10+ real migrations logged, compare to model | India data strategy (Electricity Maps schedule) | EXP-04 network kWh/GB sensitivity | |
| 8 | netem-shaped transfer profiling | forecast paper section draft | dashboard (Streamlit) | |
| 9 | Kepler/RAPL if available; else document | ablation: horizon 6/12/24 h | multi-seed runs, CIs on results | all figures drafted |
| 10 | demo script + video | — | regret analysis writeup | paper draft |
| 11 | buffer / bug fixing | buffer | buffer | internal review |
| 12 | viva prep: live demo | viva prep: forecast Q&A | viva prep: results Q&A | submission |

Weekly: 30-min sync, `pytest` green on `main`, results csvs in `results/` with the git SHA.
