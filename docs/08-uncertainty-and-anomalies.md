# Uncertainty, live track record and anomaly detector (models 2 and 3)

Both models stand on the forecaster ([07-forecaster.md](07-forecaster.md)). The forecaster says
where a grid will be; model 2 says how sure it is; model 3 says when the grid has gone somewhere
the forecaster did not expect. A forecast log ties them together.

Code: `cao/forecast/weather_blend.py` (quantile models), `cao/live/track.py` (log, scoring,
recalibration), `cao/live/anomaly.py` (detector). All figures below are from the run of 18 Nov 2026
on real grid data; the dashboard recomputes them on every run.

## The forecast log (what makes the rest checkable)

Every run writes down what it just forecast: per grid, for 1, 3, 6, 12 and 24 hours ahead, the
value, the band, the time issued (`site/data/fc_log.csv`). When that hour arrives the row is scored
against what the grid did, and against "same as now".

- Rows written by a real run are marked `live`. The dashboard's "live track record" counts only those.
- On first start the log is back-filled for the last two weeks with what the models *that existed
  then* would have issued (trained only on earlier data), marked `backfill`. It gives the detector
  and the recalibration something to work with from day one, and it is never counted as live.
- The log keeps 30 days.

## Model 2: how sure is the forecast

**What it is.** Two more boosted-tree models per grid, same inputs and same limits on complexity as
the forecaster, trained with a quantile loss: one predicts the 10th percentile of the change from
now, the other the 90th. Together they give a band meant to hold the true value 80 % of the time.
Unlike a fixed ± figure, the band is wide when the weather forecast makes the outcome open and
narrow when it does not.

**Calibration, step one (training time).** Raw quantile models are usually too narrow. On the 14
held-out days we measure how far outside the raw band the truth fell and widen each horizon band
by the 80th percentile of that miss (conformalised quantile regression).

**Calibration, step two (live).** The grid drifts after training, so the band is checked again
against the forecast log. Before a forecast is shown, its band is widened by what the last 7 days
of *already checked* forecasts say it needed. It can only widen, never go narrower than the model's
own band. The log stores the model's own band, so the adjustment never feeds on itself.

**Does it work?** Walk-forward on the log: each of 7,210 forecasts over two weeks is judged with an
adjustment computed only from forecasts checked before it was issued.

| grid | model's own band held | after live recalibration | aim |
| --- | --- | --- | --- |
| London | 78.0 % | 82.8 % | 80 % |
| South Wales | 80.9 % | 82.3 % | 80 % |
| France | 63.2 % | 79.7 % | 80 % |
| Denmark West | 70.7 % | 77.3 % | 80 % |
| North West England | 70.1 % | 77.1 % | 80 % |
| all five | 72.6 % | 79.8 % | 80 % |

The price is a band about 16 % wider on average (50 → 58 gCO₂/kWh). France shows why the live step
matters: its errors grew after the calibration days and the fixed band was holding 63 %.

**Against the simpler band.** The first version was one ± figure per horizon (80th percentile of
past absolute error). On 28 unseen days it held 73 %; the quantile band held 76 % and scored
better on the interval score (109.0 against 117.2, lower is better), so it is both better
calibrated and sharper.

**Tried and rejected.**

- *A second calibration pass on the held-out days*: 76 % → 77 %. Not worth a second layer; the
  rolling live step does the job because it sees the recent drift.
- *Using the band to veto WAIT* (only wait if the pessimistic edge of the band still says waiting
  pays). It removed 96 % of the waits and the benefit with them. The band is wide exactly at the
  horizons where waiting pays, so a pessimistic rule never waits. The option stays in the engine
  (`risk_aware`, off by default) so the experiment can be repeated.

**Honest limits.** The 7-day window and the widen-only rule were picked on the same two weeks the
table reports, so expect the live figure to sit a little lower; the dashboard's live track record
is the untouched test. Two grids are still a few points under 80 %. The band is for one hour at a
time; it says nothing about a whole day being above or below.

## Model 3: when is the grid behaving unusually

**What it is.** A detector on the forecast log. For every completed hour it takes the forecast
made three hours earlier and asks how far the grid landed from it.

1. Gap = actual − forecast, centred on the grid's median gap.
2. Scale = that grid's usual forecast error over the last two weeks (median absolute deviation, a
   spread measure that a few wild hours cannot inflate).
3. Alarm line = 3× the usual error, or higher: at least the level only about 1 hour in 100 of that
   grid's own recent hours crosses.
4. An hour is unusual when it is past the alarm line **and** outside the forecast band that was
   shown. Neighbouring unusual hours merge into one event.
5. First explanation: compare the wind that blew with the wind that had been forecast for that
   hour. If wind explains the direction of the miss it says so; if not it says wind does not
   explain it.

**Why the alarm line is per grid.** The first version used 3× for every grid and flagged 6.2 % of
all hours: France 9.4 %, South Wales 8.5 %, North West England 6.6 %, against 1.1–1.4 % for London
and Denmark. Those three grids have heavy-tailed errors (South Wales: usual error 17 g, standard
deviation 36 g), so a fixed multiple calls their ordinary bad hours unusual. With the per-grid
line the detector flags 0.95 % of 1,679 grid-hours, 11 events in the last seven days. Alarm lines
on 18 Nov: London and Denmark 3.4×, North West England 5.5×, France 5.7×, South Wales 8.2×.

**What it is not.** There is no labelled list of real grid incidents to score against, so there is
no "accuracy" for this model. What can be stated: the alarm rate (about 1 %), that it is the same
rule for every grid, and each event with its numbers so anyone can check it against the chart.
The 1-in-100 line is set from the same two weeks it judges, so a long event raises its own bar and
shows up as its worst hours rather than its full length. The explanation covers wind only; "plant
outages, imports or demand" is a pointer, not a diagnosis.

**Use.** It is shown, not acted on: the cards carry an UNUSUAL tag, the Events section lists the
week. Feeding it into decisions (hold moves into a grid that is misbehaving) is a later step and
would need its own study first.

## Showing it live

1. Forecast section: point at the shaded band, then the line "Shaded band held the true value":
   the percentage before and after live recalibration, and the number of checked forecasts.
2. Same panel, "Live track record": forecasts issued by the hosted runs and already checked,
   error against naive. It starts at zero after a fresh deploy and grows every hour.
3. Model section: the "Uncertainty band" row, including how much the band is widened right now.
4. Events section: the list of the week's unusual hours with expected value, band, actual value and
   the wind check; on the right, how close each grid is to its alarm line at this moment.
5. `cao live tick` prints the same numbers in the terminal.

## Likely questions

- *Is the band just ± average error?* No. Separate models for the 10th and 90th percentile, then two
  calibration steps. The simple band was the baseline and lost.
- *How do you know 80 % means 80 %?* It is counted: 79.8 % over 7,210 forecasts, each judged only
  with information available before it was issued. The live counter keeps counting.
- *Does the scheduler use the band?* Not for decisions. We tested it and it made the result worse;
  the table above says so. It is shown to people and used by the anomaly detector.
- *How accurate is the anomaly detector?* It cannot be scored without labelled incidents. Its alarm
  rate is about 1 hour in 100 and every flag is shown with the evidence.
- *Is anything here pre-trained or an API call to an AI service?* No. All three models are trained
  in this repository on data the pipeline collected, and retrained on every run.
