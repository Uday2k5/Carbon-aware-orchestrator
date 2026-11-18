# The carbon forecaster (model 1)

What it is for: the scheduler can only decide to WAIT for a cleaner hour, or judge whether a MOVE
will still pay back in six hours, if it knows where each grid is heading. This model predicts the
carbon intensity of every grid for each of the next 24 hours. It is trained by this project on the
data the pipeline collects, retrained on every run, and scored every day on days it has not seen.

Code: `cao/forecast/weather_blend.py` (model), `cao/live/weather.py` (weather inputs),
`cao/live/forecasting.py` (training, daily scoring, forecast-value study).
Reproduce the numbers below: `cao live tick` then `python experiments/exp06_forecaster_study.py`.

## Design

1. **Target: the change from now**, `CI(t+h) − CI(t)` for h = 1…24. Predicting the change keeps the
   forecast anchored to the latest measured value.
2. **Inputs**
   - recent history: lags 1, 2, 3, 6, 12, 24, 48, 168 h, rolling mean and spread;
   - calendar of the origin hour and of the target hour (hour of day, weekday, weekend);
   - **day-ahead weather forecast for the target hour**: wind at 100 m (mean, peak and capped cube
     as a wind-power proxy), sunshine, temperature, cloud, averaged over 3–4 points per grid, plus how
     much wind, sun and temperature change between now and then. Source: Open-Meteo, using the
     forecast *as it was issued one day earlier*, so training sees the same quality of information
     the model has when it runs live.
3. **Model: small gradient-boosted trees.** 15 leaves, at least 40 samples per leaf, L2 = 1,
   learning rate 0.05, with the physical constraint that more wind can only lower the prediction.
4. **Rounds chosen on held-out time.** The most recent 14 days are held out; the number of boosting
   rounds is the one that minimises error there, then the model is refit on everything.
5. **Blend layer, learned on the same held-out days, per horizon band** (1, 2–3, 4–6, 7–12, 13–24 h):
   `forecast = now + s·(trees' change) + u·(same hour yesterday − now)`.
   A band only moves away from "same as now" if that improves held-out error by at least 5 %, so
   where the trees are weak the forecast falls back to the naive value by itself.
6. **Uncertainty band:** its own model, see [08-uncertainty-and-anomalies.md](08-uncertainty-and-anomalies.md).
7. **Fallbacks:** a grid with under four weeks of history gets "same hour yesterday", under two
   days "same as now". The dashboard says which is in use.

## How the design was chosen (walk-forward, 28 unseen days)

For each of the last four weeks a model is trained only on data before that week and asked for a
24 h forecast four times a day (about 110 forecasts × 24 hours per grid). Mean error in gCO₂/kWh,
run of 18 Nov 2026:

| grid | same as now | same hour yesterday | first version (default trees, no weather) | final, no weather | **final** | skill vs best naive |
| --- | --- | --- | --- | --- | --- | --- |
| North West England | 13.3 | 14.2 | 15.2 | 12.3 | **12.0** | 9 % |
| London | 35.9 | 38.0 | 54.9 | 34.2 | **28.8** | 20 % |
| South Wales | 47.9 | 49.1 | 70.5 | 45.9 | **41.5** | 13 % |
| Denmark West | 31.3 | 38.8 | 35.4 | 29.3 | **25.4** | 19 % |
| France | 8.1 | 8.6 | 8.6 | 7.3 | **7.5** | 8 % |

What the columns show:

- **The first version overfitted.** Default settings memorised the training period (London: error 7.9
  on days it had seen, 36.1 on days it had not) and lost to the naive methods in London and South Wales.
- **Regularisation fixed that** ("final, no weather" beats naive everywhere).
- **Weather adds real signal** where wind drives the grid: London 34.2 → 28.8, Denmark 29.3 → 25.4,
  South Wales 45.9 → 41.5. It adds nothing in nuclear-dominated France.

Things tried and dropped because they did not help on unseen data: a linear (ridge) model, an
average of trees and ridge, time-decay sample weights, and a bias correction from recent residuals
(helped one grid, hurt three).

## Over- and under-fitting check (final model, error of the predicted change)

| grid | days it trained on | held-out days, trees | held-out days, after blend | unseen test weeks |
| --- | --- | --- | --- | --- |
| North West England | 6.3 | 10.3 | 8.4 | 12.0 |
| London | 20.7 | 29.7 | 26.0 | 28.8 |
| South Wales | 35.5 | 60.0 | 48.4 | 41.5 |
| Denmark West | 19.5 | 24.5 | 22.5 | 25.4 |
| France | 4.2 | 7.5 | 6.4 | 7.5 |

Not overfitting: the gap between seen and unseen days is modest, and unseen-day error stays below
the naive methods. Not underfitting: it beats both naive baselines and the no-weather ablation.
The dashboard shows the same four bars per grid, refreshed on every run.

## What the forecast is worth to the scheduler

Same jobs, same real grid data, three forecasts handed to the scheduler: naive ("same as now"), our
model (each hour using a model that existed at that hour), perfect foresight. Jobs stop arriving two
days before the end so every variant finishes the same work. `experiments/exp07_forecast_value.py`,
28 days to 18 Nov 2026, two independent job streams, emissions in kg:

| scheduler | naive forecast | our model | perfect foresight | model vs naive | perfect vs naive |
| --- | --- | --- | --- | --- | --- |
| payback rule (greedy) | 26.85 | 26.76 | 25.56 | 0.3 % lower | 4.8 % lower |
| 24 h MILP plan | 26.95 | 26.31 | 24.41 | 2.4 % lower | 9.4 % lower |

Reading it straight:

- The forecast is a **small lever**. Even a perfect forecast is worth 5 to 9 %. The large savings
  on the scoreboard (against carbon-unaware and always-greenest) come from the payback rule itself,
  which refuses moves that never repay their own carbon. That part needs no forecast.
- The **MILP gets more out of the same forecast** (2.4 % against 0.3 %), because it plans the whole
  day; the greedy rule only uses the forecast to decide whether to wait.
- With the greedy rule the gain is inside the noise between job streams. A second run with four
  streams gave 1.1 %; the dashboard's own rolling study (about 12 days, three streams) showed 0.6 % on 18 Nov.
- An earlier single-week run showed 4.1 % and "58 % of perfect foresight". That week was a
  favourable draw, not the typical result, and those figures are withdrawn.

The dashboard repeats the greedy study once a day on its latest window and shows whatever it finds.
The live scoreboard also carries a line "ours · naive forecast"; over a few days that gap is one
draw and swings a lot, so quote the study rather than the gap.

## Honest limits

- About 90 days of history, one season. Expect the numbers to move; the daily score on the
  dashboard is the one to quote, with its date.
- In the first one to three hours "same as now" is as good or better; the model's edge starts
  around four hours ahead, which is where waiting decisions need it.
- Weather comes from 3–4 points per grid, not a full wind-farm map.
- The forecast-value figures depend on the placeholder migration cost constants and on the
  simulated job mix.
- India joins as a naive forecast first and gets the trained model after four weeks of collected data.

## Likely questions

- *Did you train it or download it?* Trained here, every run, on data the pipeline collected. No pre-trained model.
- *How do you know it is not overfitting?* Rounds and blend weights are picked on the latest 14 days,
  never on training data; the walk-forward test scores only unseen days; the first version did overfit and the table shows it.
- *Why trees and not a neural network?* Two thousand hourly points per grid is small tabular data;
  boosted trees are the right tool at that size. An LSTM would be compared, not expected to win.
- *What does it use?* Mostly the current value, the hour of day and the wind forecast; the dashboard lists the drivers per grid.
- *Does it matter?* Forecast error is about a fifth lower in the wind-driven grids. For emissions the forecast is a small lever:
  about 2 % with the MILP plan and under 1 % with the greedy rule, where perfect foresight would give 5 to 9 %. The big saving is the payback rule.
- *Then why build it?* Three things stand on it: the WAIT decision and the MILP plan, the uncertainty band, and the anomaly detector
  (an hour can only be called unusual against an expectation).
