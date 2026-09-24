"""EXP-02  All baselines vs proposed policy vs oracle on the same jobs and traces.

    python experiments/exp02_policy_comparison.py [--data data/processed/ci.csv] [--seeds 3]
"""
import argparse

import pandas as pd

from _common import RESULTS, load_cost_model, load_settings
from cao.carbon.schema import strip_index, to_traces
from cao.carbon.sources.synthetic import generate_dataset
from cao.simulator import NoisyForecast, compare_policies, default_policies, generate_jobs
from cao.simulator.metrics import summarize

ap = argparse.ArgumentParser()
ap.add_argument("--data", help="normalized CI csv (default: synthetic)")
ap.add_argument("--hours", type=int, default=24 * 7)
ap.add_argument("--jobs", type=int, default=20)
ap.add_argument("--seeds", type=int, default=1)
ap.add_argument("--sigma", type=float, default=0.10, help="forecast error (relative)")
ap.add_argument("--no-milp", action="store_true")
ap.add_argument("--replan-every", type=int, default=1, help="MILP re-solve interval (slots); 3 is ~3x faster")
args = ap.parse_args()

settings = load_settings()
cm = load_cost_model(settings)
frames = []
for seed in range(args.seeds):
    if args.data:
        traces = strip_index(to_traces(pd.read_csv(args.data), hours=args.hours))
    else:
        df = generate_dataset(settings.region_names, days=max(1, args.hours // 24), seed=seed)
        traces = strip_index(to_traces(df, hours=args.hours))
    T = min(len(v) for v in traces.values())
    jobs = generate_jobs(args.jobs, list(traces), horizon_h=float(T), seed=seed)
    pols = default_policies(traces, include_milp=not args.no_milp)
    for p in pols:
        if hasattr(p, "replan_every"):
            p.replan_every = args.replan_every
    df = compare_policies(traces, jobs, pols, cm, latency_ms=settings.latency_ms,
                          capacity=settings.capacity_cpu, forecast=NoisyForecast(traces, args.sigma, seed))
    df["seed"] = seed
    frames.append(df)
    print(f"\n== seed {seed}  ({T} h, {len(jobs)} jobs, cost model {cm.source}) ==")
    with pd.option_context("display.width", 220, "display.max_columns", 30):
        print(df.to_string(index=False))

out = pd.concat(frames, ignore_index=True)
out.to_csv(RESULTS / "exp02_policy_comparison.csv", index=False)
if args.seeds > 1:
    print("\n== mean over seeds ==")
    print(summarize(frames).round(1).to_string(index=False))
print(f"\n-> {RESULTS}/exp02_policy_comparison.csv")
