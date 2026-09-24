"""EXP-05  Visual replay for presentations: JSON export + self-contained HTML page + GIF.

    python experiments/exp05_replay.py [--hours 72] [--jobs 16] [--policy migration-aware-milp] [--no-gif]
"""
import argparse

import pandas as pd

from _common import RESULTS, load_cost_model, load_settings
from cao.carbon.schema import strip_index, to_traces
from cao.carbon.sources.synthetic import generate_dataset
from cao.replay.export import export_replay, load_replay
from cao.replay.html import render_html
from cao.simulator import NoisyForecast, compare_policies, default_policies, generate_jobs

ap = argparse.ArgumentParser()
ap.add_argument("--data", help="normalized CI csv (default: synthetic)")
ap.add_argument("--hours", type=int, default=72)
ap.add_argument("--jobs", type=int, default=16)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--sigma", type=float, default=0.10)
ap.add_argument("--policy", default=None, help="policy to animate (default: migration-aware-milp)")
ap.add_argument("--fps", type=int, default=4)
ap.add_argument("--no-gif", action="store_true")
ap.add_argument("--mp4", action="store_true", help="also write MP4 (needs ffmpeg)")
args = ap.parse_args()

settings = load_settings()
cm = load_cost_model(settings)
df = pd.read_csv(args.data) if args.data else generate_dataset(settings.region_names, days=max(1, args.hours // 24), seed=args.seed)
tr_full = to_traces(df, hours=args.hours)
stamps = tr_full.pop("__index__")
traces = strip_index(tr_full)
T = min(len(v) for v in traces.values())
jobs = generate_jobs(args.jobs, list(traces), horizon_h=float(T), seed=args.seed)
pols = default_policies(traces, include_milp=True)
table = compare_policies(traces, jobs, pols, cm, latency_ms=settings.latency_ms, capacity=settings.capacity_cpu,
                         forecast=NoisyForecast(traces, args.sigma, args.seed), record_timeline=True)
with pd.option_context("display.width", 220, "display.max_columns", 30):
    print(table[["policy", "total_g", "migration_g", "migrations", "waits", "refuses", "deadline_violations", "regret_g"]].to_string(index=False))

json_path = export_replay(RESULTS / "replay.json", traces, jobs, table.attrs["results"], cm, timestamps=stamps)
html_path = render_html(load_replay(json_path), RESULTS / "replay.html")
print(f"\nreplay json -> {json_path}\nreplay html -> {html_path}   (double-click; works offline)")
if not args.no_gif:
    from cao.replay.animate import render_animation
    out = render_animation(load_replay(json_path), args.policy, RESULTS / "replay.gif",
                           RESULTS / "replay.mp4" if args.mp4 else None, fps=args.fps)
    print(f"replay gif  -> {out['gif']}" + (f"\nreplay mp4  -> {out['mp4']}" if out.get("mp4") else ""))
