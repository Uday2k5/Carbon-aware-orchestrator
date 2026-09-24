# Notebooks (Member 2 — forecasting)

Suggested notebooks (Jupyter, Windows is fine):

1. `01_explore_ci.ipynb` — load `data/processed/ci_*.csv`, plot diurnal/weekly patterns per region.
2. `02_features.ipynb` — reproduce `cao.forecast.features.make_supervised`, inspect lag importance.
3. `03_models.ipynb` — persistence vs seasonal-naive vs gradient boosting vs XGBoost, MAE/MAPE per horizon
   (`cao.forecast.evaluate.compare_models`).
4. `04_uncertainty.ipynb` — residual spread per horizon; how forecast error changes scheduler decisions
   (feeds `experiments/exp03_forecast_sensitivity.py`).

Keep model code in `cao/forecast/`, notebooks only call it.
