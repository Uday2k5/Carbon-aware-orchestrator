"""`cao` command line.

  cao carbon synth  --days 30 --out data/processed/ci.csv [--store]
  cao carbon fetch  --source uk --region uk --grid GB --start 2026-01-01 --end 2026-02-01 --out ...
  cao profile       [--sizes 0.1,0.5,1] [--smoke] [--repeats 1] [--transport loopback]
  cao fit           results/migration_profile.csv [--out config/migration_model.json]
  cao payback       --state-gb 60 --power-kw 0.2 --ci-src 650 --ci-dst 50 --remaining-h 0.5
  cao boundary      --power-kw 0.2 --ci-src 650 --ci-dst 50 [--sizes ...]
  cao forecast      --data data/processed/ci.csv --region uk [--model gbr]
  cao simulate      --data data/processed/ci.csv --jobs 20 --seed 1 [--no-milp] [--export results/replay.json]
  cao replay        results/replay.json --html results/replay.html --gif results/replay.gif [--mp4 ...] [--policy X]
  cao live tick     [--site site]          # real grid data -> forecast -> decisions -> dashboard json
  cao live serve    [--site site] [--port 8080]
  cao controller    [--dry-run] [--fake] [--interval 300] [--mode heuristic|milp]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .core.config import load_settings
from .core.models import Job
from .migration.cost_model import MigrationCostModel


def _settings(args):
    return load_settings(getattr(args, "config", None))


def _cost_model(args, s):
    p = getattr(args, "model", None) or os.environ.get("CAO_MIGRATION_MODEL", "config/migration_model.json")
    if p and os.path.exists(p):
        cm = MigrationCostModel.from_json(p)
    else:
        cm = MigrationCostModel.from_config(s.migration_model, s.network)
    if getattr(args, "network_kwh_per_gb", None) is not None:
        cm.network_kwh_per_gb = args.network_kwh_per_gb
    return cm


# ----------------------------------------------------------------------------- carbon
def cmd_carbon_synth(args):
    from .carbon.sources.synthetic import generate_dataset
    s = _settings(args)
    df = generate_dataset(args.regions or s.region_names, days=args.days, seed=args.seed)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"wrote {len(df)} rows -> {args.out}")
    if args.store:
        from .db.store import Database
        print(f"stored {Database().upsert_carbon(df)} rows in sqlite")


def cmd_carbon_fetch(args):
    from .carbon.sources import get_source
    src = get_source(args.source)
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    df = src.fetch(args.region, args.grid, start, end)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        header = not (args.append and os.path.exists(args.out))
        df.to_csv(args.out, index=False, mode="a" if args.append else "w", header=header)
        print(f"wrote {len(df)} rows -> {args.out}")
    else:
        print(df.to_string(index=False))
    if args.store:
        from .db.store import Database
        print(f"stored {Database().upsert_carbon(df)} rows in sqlite")


# ---------------------------------------------------------------------------- profile
def cmd_profile(args):
    from .energy.power_model import UtilizationPowerModel
    from .migration.profiler import DEFAULT_SIZES_GB, SMOKE_SIZES_GB, profile
    s = _settings(args)
    sizes = SMOKE_SIZES_GB if args.smoke else (
        [float(x) for x in args.sizes.split(",")] if args.sizes else DEFAULT_SIZES_GB)
    pm = UtilizationPowerModel.from_config(s.power_model)
    df = profile(sizes, args.workdir, pm, args.transport, args.repeats, use_rapl=not args.no_rapl)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"wrote {len(df)} measurements -> {args.out}")
    if args.store:
        from .db.store import Database
        Database().insert_df("migration_measurements", df)


def cmd_fit(args):
    s = _settings(args)
    df = pd.read_csv(args.measurements)
    cm = MigrationCostModel.fit(df, s.network.get("energy_kwh_per_gb", 0.06),
                                s.network.get("ci_attribution", "mean"))
    cm.to_json(args.out)
    print(json.dumps(cm.to_dict(), indent=2))
    print(f"-> {args.out}")


# ---------------------------------------------------------------------------- decide
def cmd_payback(args):
    from .decision.simple import decide_simple
    s = _settings(args)
    cm = _cost_model(args, s)
    job = Job("job", "batch-processing", args.power_kw, args.remaining_h, args.state_gb, "src",
              running=True, started=True)
    d = decide_simple(job, {"src": args.ci_src, "dst": args.ci_dst}, cm)
    mc = cm.carbon_g(args.state_gb, args.ci_src, args.ci_dst)
    print(f"decision      : {d.action.value}")
    print(f"reason        : {d.reason}")
    print(f"saved         : {d.saved_g:8.1f} g   (P={args.power_kw} kW x dCI={args.ci_src - args.ci_dst:.0f} x {args.remaining_h} h)")
    print(f"migration     : {mc.total_g:8.1f} g   [ckpt {mc.checkpoint_g:.2f} + xfer {mc.transfer_g:.2f} + network {mc.network_g:.1f} + restore {mc.restore_g:.2f}]")
    print(f"payback       : {d.payback_h:8.2f} h   remaining {args.remaining_h} h")
    print(f"downtime est. : {mc.downtime_s:8.1f} s")
    print(f"cost model    : {cm.source}, network {cm.network_kwh_per_gb} kWh/GB")


def cmd_boundary(args):
    from .decision.payback import payback_boundary
    s = _settings(args)
    cm = _cost_model(args, s)
    sizes = [float(x) for x in args.sizes.split(",")]
    print(f"{'state_gb':>9} {'migration_g':>12} {'payback_h':>10}   rule: MOVE iff remaining_h > payback_h")
    for p in payback_boundary(args.power_kw, args.ci_src, args.ci_dst, sizes, cm):
        print(f"{p.state_gb:9.2f} {p.migration_g:12.1f} {p.payback_h:10.2f}")


# --------------------------------------------------------------------------- forecast
def cmd_forecast(args):
    from .forecast.evaluate import compare_models
    from .forecast.models import make_forecaster
    df = pd.read_csv(args.data)
    d = df[df["region"] == args.region].copy()
    if d.empty:
        sys.exit(f"no rows for region {args.region!r}")
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    series = d.set_index("timestamp")["ci_g_per_kwh"].astype(float)
    if args.evaluate:
        print(compare_models(series, args.horizon, args.origins, include_xgboost=args.model == "xgb"))
        return
    m = make_forecaster(args.model, max_horizon=args.horizon) if args.model in ("gbr", "xgb") else make_forecaster(args.model)
    m.fit(series)
    lo, pt, hi = m.predict_interval(series, args.horizon)
    print(f"{args.model} forecast for {args.region} from {series.index[-1]}:")
    for h, (a, b, c) in enumerate(zip(lo, pt, hi), 1):
        print(f"  +{h:2d}h  {b:7.1f}   [{a:6.1f}, {c:6.1f}]")


# --------------------------------------------------------------------------- simulate
def cmd_simulate(args):
    from .carbon.schema import strip_index, to_traces
    from .carbon.sources.synthetic import generate_dataset
    from .simulator import NoisyForecast, compare_policies, default_policies, generate_jobs
    s = _settings(args)
    cm = _cost_model(args, s)
    if args.data:
        df = pd.read_csv(args.data)
        traces = strip_index(to_traces(df, args.regions or None, hours=args.hours))
    else:
        df = generate_dataset(args.regions or s.region_names, days=max(1, args.hours // 24), seed=args.seed)
        traces = strip_index(to_traces(df, hours=args.hours))
    T = min(len(v) for v in traces.values())
    jobs = generate_jobs(args.jobs, list(traces), horizon_h=T * 1.0, seed=args.seed)
    pols = default_policies(traces, include_milp=not args.no_milp, include_oracle=not args.no_oracle)
    for p_ in pols:
        if hasattr(p_, "replan_every"):
            p_.replan_every = args.replan_every
    fc = NoisyForecast(traces, sigma_rel=args.forecast_sigma, seed=args.seed)
    res = compare_policies(traces, jobs, pols, cm, latency_ms=s.latency_ms, capacity=s.capacity_cpu,
                           forecast=fc, horizon_slots=int(s.scheduler.get("horizon_slots", 24)),
                           record_timeline=bool(args.export))
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(res.to_string(index=False))
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        res.to_csv(args.out, index=False)
        print(f"-> {args.out}")
    if args.export:
        from .replay.export import export_replay
        stamps = to_traces(df, hours=args.hours).get("__index__") if args.data else None
        path = export_replay(args.export, traces, jobs, res.attrs["results"], cm, timestamps=stamps)
        print(f"replay -> {path}   (cao replay {path} --html ... --gif ...)")


# ----------------------------------------------------------------------------- replay
def cmd_replay(args):
    from .replay.export import load_replay
    from .replay.html import render_html
    rep = load_replay(args.replay)
    if not (args.html or args.gif or args.mp4):
        sys.exit("nothing to do: pass --html and/or --gif / --mp4")
    if args.html:
        print(f"html -> {render_html(rep, args.html)}   (open in any browser; no server needed)")
    if args.gif or args.mp4:
        from .replay.animate import render_animation
        out = render_animation(rep, args.policy, args.gif, args.mp4, fps=args.fps, dpi=args.dpi, hours=args.hours)
        for k, v in out.items():
            if v:
                print(f"{k} -> {v}")


# ------------------------------------------------------------------------------- live
def cmd_live_tick(args):
    from .live.pipeline import tick
    out = tick(args.site, args.live_config)
    print(f"tick @ {out['now']}  ({out['seconds']} s)")
    for lid, st in out["status"].items():
        print(f"  {lid:<20} {st:<13} {out['rows'].get(lid, 0):>6} readings fetched" + (f"   {out['errors'][lid]}" if lid in out["errors"] else ""))
    print(f"  weather forecasts for: {', '.join(out['weather']) or 'none'}")
    for lid, a in out["accuracy"].items():
        print(f"  forecast error {lid:<20} ours {a['mae_ours']:>5}  same-as-now {a['mae_persistence']:>5}  yesterday {a['mae_seasonal']:>5}   skill {a['skill_pct']:>5} %  band hit {a.get('band_hit_pct')} %  ({a['n_forecasts']} forecasts)")
    v = out.get("forecast_value")
    if v:
        print(f"  forecast value ({v['days']} days x {v['streams']} job streams): naive {v['naive_g']:,.0f} g  our model {v['model_g']:,.0f} g ({v['saved_pct']} % lower)  perfect {v['perfect_g']:,.0f} g ({v['perfect_pct']} % lower)")
    for lid, t in (out.get("track") or {}).items():
        rc = t.get("recal")
        if rc:
            live_part = f"   live forecasts checked: {t['live_scored']}" + (f" (error {t['mae']} vs naive {t['naive_mae']})" if t.get("live_scored") else "")
            print(f"  uncertainty band {lid:<20} model's own {rc['model_band_hit_pct']:>5} %  recalibrated live {rc['hit_pct']:>5} %  (aim {rc['target_pct']:.0f} %, {rc['n']} checked forecasts){live_part}")
    an = out.get("anomalies") or {}
    if an.get("hours_checked"):
        print(f"  anomaly detector: {an['hours_checked']} grid-hours checked, {an['alarm_rate_pct']} % flagged, {len(an['events'])} events in the last 7 days")
        for e in an["events"][:4]:
            print(f"     {e['location']:<20} {e['peak'][:16]}  {e['actual']:.0f} vs {e['expected']:.0f} expected  {e['z']:+.1f}x usual error (alarm line {e['limit']})  {e['why']['text']}")
    print(f"  hours processed: {out['hours_processed']}   new decisions: {out['new_decisions']}")
    print("  cumulative gCO2e: " + "  ".join(f"{k}={v:,.0f}" for k, v in out["totals"].items()))
    print(f"  dashboard: {out['site']}/index.html   (cao live serve --site {out['site']})")


def cmd_live_serve(args):
    import functools
    import http.server
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=args.site)
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as srv:
        print(f"serving {args.site} at http://localhost:{args.port}  (Ctrl+C to stop)")
        srv.serve_forever()


# ------------------------------------------------------------------------- controller
def cmd_controller(args):
    from .decision.engine import DecisionEngine
    from .k8s.controller import Controller
    s = _settings(args)
    cm = _cost_model(args, s)
    engine = DecisionEngine(cm, s.region_names, s.latency_ms, s.capacity_cpu,
                            slot_h=float(s.scheduler.get("slot_hours", 1.0)),
                            margin_g=float(s.scheduler.get("margin_g", 0.0)),
                            evaluation_horizon_h=float(s.scheduler.get("evaluation_horizon_h", 24)),
                            horizon_slots=int(s.scheduler.get("horizon_slots", 24)),
                            milp_time_limit_s=float(s.scheduler.get("milp_time_limit_s", 20)))

    def ci_provider():
        # latest stored CI per region, persisted forward (swap in the forecaster for real use)
        from .db.store import Database
        df = Database().load_carbon(s.region_names)
        out = {}
        for r in s.region_names:
            d = df[df["region"] == r]
            val = float(d["ci_g_per_kwh"].iloc[-1]) if len(d) else 400.0
            out[r] = [val] * engine.horizon_slots
        return out

    if args.fake:
        from .k8s import constants as C
        from .k8s.client import FakeKubeClient, PodInfo
        pods = [PodInfo("ml-training-abc", "cao", "node-india",
                        labels={C.MANAGED_LABEL: "true", C.DEPLOYMENT_LABEL: "ml-training"},
                        annotations={C.ANN_KIND: "ml-training", C.ANN_POWER_KW: "0.2",
                                     C.ANN_STATE_GB: "0.2", C.ANN_REMAINING_H: "3"})]
        kube = FakeKubeClient(pods, {"node-india": "india", "node-sweden": "sweden",
                                     "node-france": "france", "node-us": "us-east", "node-uk": "uk"})
    else:
        from .k8s.client import KubernetesClient
        kube = KubernetesClient(args.kubeconfig, args.context)
    from .db.store import Database
    ctl = Controller(kube, engine, ci_provider, db=Database(), mode=args.mode, dry_run=args.dry_run,
                     checkpoints_dir=args.checkpoints_dir, namespace=args.namespace)
    ctl.run(interval_s=args.interval, max_ticks=args.ticks)


# --------------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cao", description="Carbon-Aware Autonomous Workload Orchestrator")
    p.add_argument("--config", help="path to regions.yaml")
    p.add_argument("--model", help="path to fitted migration_model.json")
    p.add_argument("--network-kwh-per-gb", type=float, help="override network energy intensity")
    sp = p.add_subparsers(dest="cmd", required=True)

    c = sp.add_parser("carbon").add_subparsers(dest="sub", required=True)
    a = c.add_parser("synth"); a.add_argument("--days", type=int, default=30); a.add_argument("--seed", type=int, default=0)
    a.add_argument("--regions", nargs="*"); a.add_argument("--out", default="data/processed/ci_synthetic.csv")
    a.add_argument("--store", action="store_true"); a.set_defaults(func=cmd_carbon_synth)
    a = c.add_parser("fetch"); a.add_argument("--source", required=True); a.add_argument("--region", required=True)
    a.add_argument("--grid", required=True); a.add_argument("--start", required=True); a.add_argument("--end", required=True)
    a.add_argument("--out"); a.add_argument("--append", action="store_true"); a.add_argument("--store", action="store_true")
    a.set_defaults(func=cmd_carbon_fetch)

    a = sp.add_parser("profile"); a.add_argument("--sizes"); a.add_argument("--smoke", action="store_true")
    a.add_argument("--repeats", type=int, default=1); a.add_argument("--transport", default="loopback", choices=["loopback", "copy", "netem"])
    a.add_argument("--workdir", default="/tmp/cao-profile"); a.add_argument("--out", default="results/migration_profile.csv")
    a.add_argument("--no-rapl", action="store_true"); a.add_argument("--store", action="store_true"); a.set_defaults(func=cmd_profile)

    a = sp.add_parser("fit"); a.add_argument("measurements"); a.add_argument("--out", default="config/migration_model.json")
    a.set_defaults(func=cmd_fit)

    a = sp.add_parser("payback"); a.add_argument("--state-gb", type=float, required=True); a.add_argument("--power-kw", type=float, required=True)
    a.add_argument("--ci-src", type=float, required=True); a.add_argument("--ci-dst", type=float, required=True)
    a.add_argument("--remaining-h", type=float, required=True); a.set_defaults(func=cmd_payback)

    a = sp.add_parser("boundary"); a.add_argument("--power-kw", type=float, required=True); a.add_argument("--ci-src", type=float, required=True)
    a.add_argument("--ci-dst", type=float, required=True); a.add_argument("--sizes", default="0.1,0.2,0.5,1,2,5,10,20,60")
    a.set_defaults(func=cmd_boundary)

    a = sp.add_parser("forecast"); a.add_argument("--data", required=True); a.add_argument("--region", required=True)
    a.add_argument("--model", default="gbr", choices=["persistence", "seasonal", "gbr", "xgb"]); a.add_argument("--horizon", type=int, default=24)
    a.add_argument("--evaluate", action="store_true"); a.add_argument("--origins", type=int, default=20); a.set_defaults(func=cmd_forecast)

    a = sp.add_parser("simulate"); a.add_argument("--data"); a.add_argument("--regions", nargs="*"); a.add_argument("--hours", type=int, default=24 * 3)
    a.add_argument("--jobs", type=int, default=20); a.add_argument("--seed", type=int, default=1); a.add_argument("--forecast-sigma", type=float, default=0.1)
    a.add_argument("--no-milp", action="store_true"); a.add_argument("--no-oracle", action="store_true"); a.add_argument("--out")
    a.add_argument("--replan-every", type=int, default=1, help="MILP re-solve interval in slots")
    a.add_argument("--export", help="write replay JSON for `cao replay`"); a.set_defaults(func=cmd_simulate)

    a = sp.add_parser("replay", help="render a replay JSON as HTML page and/or GIF/MP4 animation")
    a.add_argument("replay"); a.add_argument("--html"); a.add_argument("--gif"); a.add_argument("--mp4")
    a.add_argument("--policy", help="policy to animate (default: migration-aware-milp)"); a.add_argument("--fps", type=int, default=4)
    a.add_argument("--dpi", type=int, default=100); a.add_argument("--hours", type=int, help="animate only the first N hours")
    a.set_defaults(func=cmd_replay)

    lv = sp.add_parser("live", help="live demo: real grid data -> forecast -> decisions -> dashboard").add_subparsers(dest="sub", required=True)
    a = lv.add_parser("tick", help="fetch live data, advance the twin, write site/data/live.json")
    a.add_argument("--site", default="site"); a.add_argument("--live-config"); a.set_defaults(func=cmd_live_tick)
    a = lv.add_parser("serve", help="serve the dashboard locally")
    a.add_argument("--site", default="site"); a.add_argument("--port", type=int, default=8080); a.set_defaults(func=cmd_live_serve)

    a = sp.add_parser("controller"); a.add_argument("--dry-run", action="store_true"); a.add_argument("--fake", action="store_true")
    a.add_argument("--interval", type=float, default=300.0); a.add_argument("--ticks", type=int); a.add_argument("--mode", default="heuristic", choices=["heuristic", "milp"])
    a.add_argument("--kubeconfig"); a.add_argument("--context"); a.add_argument("--namespace"); a.add_argument("--checkpoints-dir")
    a.set_defaults(func=cmd_controller)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
