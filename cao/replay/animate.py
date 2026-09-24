"""Matplotlib animation of a replay -> GIF (Pillow) / MP4 (ffmpeg, when installed).

    render_animation(replay, policy="migration-aware-milp", out_gif="results/replay.gif", fps=4, hours=72)

Layout: left = region columns coloured by CI with job dots (size ∝ √state, colour = kind,
hollow = waiting, red ring = REFUSE, arrow = MOVE); top right = cumulative carbon of every
policy (selected one bold); bottom right = KPIs + latest decisions.
"""
from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

KINDHEX = {"ml-training": "#f4a261", "batch-processing": "#a78bfa", "web-service": "#34d399"}
POLCOL = ["#4cc9f0", "#f4a261", "#a78bfa", "#34d399", "#f1c40f", "#ef476f", "#f8f9fa", "#ff9f1c", "#06d6a0"]
BG, PANEL, TEXT, MUTED = "#0b1016", "#121a23", "#e6edf3", "#8b98a5"


def pick_policy(replay: dict, policy: Optional[str]) -> int:
    names = [p["name"] for p in replay["policies"]]
    if policy is not None:
        if policy not in names:
            raise ValueError(f"policy {policy!r} not in export; have {names}")
        return names.index(policy)
    for i, n in enumerate(names):
        if "milp" in n and not n.startswith("oracle"):
            return i
    return len(names) - 1


def render_animation(
    replay: dict,
    policy: Optional[str] = None,
    out_gif: Optional[str] = None,
    out_mp4: Optional[str] = None,
    fps: int = 4,
    dpi: int = 100,
    hours: Optional[int] = None,
    progress: Optional[Callable[[str], None]] = print,
) -> Dict[str, Optional[str]]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import animation
    from matplotlib.colors import Normalize
    from matplotlib.gridspec import GridSpec
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    pi = pick_policy(replay, policy)
    pol = replay["policies"][pi]
    regions: List[str] = replay["meta"]["regions"]
    R = len(regions)
    T = min(replay["meta"]["hours"], len(pol["status"]), hours or 10**9)
    jobs = replay["jobs"]
    ci = replay["ci"]
    totals = [np.asarray([c["total_g"] for c in p["cum"]][:T]) for p in replay["policies"]]
    ci_all = np.concatenate([np.asarray(ci[r][:T], float) for r in regions])
    norm = Normalize(vmin=math.sqrt(ci_all.min()), vmax=math.sqrt(ci_all.max()))
    cmap = plt.get_cmap("RdYlGn_r")

    fig = plt.figure(figsize=(12.8, 7.2), dpi=dpi, facecolor=BG)
    gs = GridSpec(2, 2, width_ratios=[1.65, 1], height_ratios=[1.05, 1], figure=fig, wspace=0.08, hspace=0.18,
                  left=0.02, right=0.98, top=0.9, bottom=0.03)
    ax = fig.add_subplot(gs[:, 0])
    ax_race = fig.add_subplot(gs[0, 1])
    ax_txt = fig.add_subplot(gs[1, 1])
    for a in (ax, ax_race, ax_txt):
        a.set_facecolor(PANEL)
        for sp in a.spines.values():
            sp.set_color("#24303d")
    title = fig.suptitle("", color=TEXT, fontsize=13, x=0.02, ha="left", y=0.965)

    def draw(t: int):
        ax.clear()
        ax.set_facecolor(PANEL)
        ax.set_xlim(0, R)
        ax.set_ylim(0, 1)
        ax.set_xticks([])
        ax.set_yticks([])
        # region columns
        occupants = {i: [] for i in range(R)}
        for k in range(len(jobs)):
            s = pol["status"][t][k]
            ri = pol["region"][t][k]
            if s in (1, 2, 3) and ri >= 0:
                occupants[ri].append(k)
        for i, r in enumerate(regions):
            v = float(ci[r][t])
            ax.add_patch(FancyBboxPatch((i + 0.03, 0.01), 0.94, 0.98, boxstyle="round,pad=0,rounding_size=0.03",
                                        facecolor=cmap(norm(math.sqrt(v))), alpha=0.55, edgecolor="none"))
            ax.text(i + 0.5, 0.955, r, ha="center", va="center", color="white", fontsize=12, fontweight="bold")
            ax.text(i + 0.5, 0.915, f"{v:,.0f} gCO₂/kWh", ha="center", va="center", color="white", fontsize=9)
        # jobs
        pos = {}
        for i, ks in occupants.items():
            ncol = 3
            rows = max(1, math.ceil(len(ks) / ncol))
            rowh = min(0.16, 0.8 / rows)
            for q, k in enumerate(ks):
                pos[k] = (i + 0.2 + 0.3 * (q % ncol), 0.86 - rowh * (q // ncol) - rowh / 2)
        for k, j in enumerate(jobs):
            if k not in pos:
                continue
            s = pol["status"][t][k]
            a = pol["action"][t][k]
            x, y = pos[k]
            size = min(900.0, (7 + 6 * math.sqrt(j["state_gb"])) ** 2 * 0.9)
            col = KINDHEX.get(j["kind"], "#ccc")
            if s == 2:
                ax.scatter([x], [y], s=size, c=col, edgecolors=BG, linewidths=1.2, zorder=3)
            else:
                ax.scatter([x], [y], s=size, facecolors=col, alpha=0.25, edgecolors=col, linewidths=1.2,
                           linestyle="--", zorder=3)
            frac = pol["progress"][t][k] if pol.get("progress") else 0
            ax.text(x, y - 0.045 - 0.0006 * math.sqrt(size), f"{_short(j['job_id'])} {int(100 * frac)}%",
                    ha="center", va="top", color=TEXT, fontsize=7.5, zorder=4)
            if a in ("M", "R", "W"):
                ax.scatter([x], [y], s=size * 2.2, facecolors="none",
                           edgecolors={"M": "#4cc9f0", "R": "#ef476f", "W": "#f1c40f"}[a], linewidths=2.2, zorder=5)
            if a == "M" and t > 0:
                pr = pol["region"][t - 1][k]
                if pr >= 0 and pr != pol["region"][t][k]:
                    ax.add_patch(FancyArrowPatch((pr + 0.5, y), (x, y), arrowstyle="-|>", mutation_scale=14,
                                                 color="#4cc9f0", linestyle="--", linewidth=1.6, zorder=6))
        # race chart
        ax_race.clear()
        ax_race.set_facecolor(PANEL)
        mx = max(1.0, max(float(a[-1]) for a in totals))
        for i, arr in enumerate(totals):
            ax_race.plot(range(t + 1), arr[: t + 1] / 1000, color=POLCOL[i % len(POLCOL)],
                         lw=2.6 if i == pi else 1.1, alpha=1 if i == pi else 0.6,
                         label=replay["policies"][i]["name"])
        ax_race.axvline(t, color=TEXT, ls=":", lw=1)
        ax_race.set_xlim(0, T - 1)
        ax_race.set_ylim(0, mx / 1000 * 1.05)
        ax_race.tick_params(colors=MUTED, labelsize=8)
        ax_race.set_ylabel("cumulative kgCO₂e", color=MUTED, fontsize=9)
        ax_race.set_xlabel("hour", color=MUTED, fontsize=9)
        ax_race.legend(fontsize=7, loc="upper left", frameon=False, labelcolor=TEXT)
        # text panel
        ax_txt.clear()
        ax_txt.set_facecolor(PANEL)
        ax_txt.set_xticks([])
        ax_txt.set_yticks([])
        c = pol["cum"][t]
        mv = sum(1 for s in range(t + 1) for a in pol["action"][s] if a == "M")
        rf = sum(1 for s in range(t + 1) for a in pol["action"][s] if a == "R")
        wt = sum(1 for s in range(t + 1) for a in pol["action"][s] if a == "W")
        done = sum(1 for s in pol["status"][t] if s == 4)
        kpi = (f"total {c['total_g']:>8,.0f} g    execution {c['exec_g']:>8,.0f} g\n"
               f"migration {c['migration_g']:>6,.1f} g    migrations {c['migrations']:>3}   refused {rf:>3}\n"
               f"wait-slots {wt:>3}   done {done}/{len(jobs)}   deadline misses (final) {pol['summary']['deadline_violations']}")
        ax_txt.text(0.02, 0.96, kpi, transform=ax_txt.transAxes, va="top", color=TEXT, fontsize=8.4, family="monospace")
        ev = [e for e in pol["events"] if e["t"] <= t]
        ev.sort(key=lambda e: -e["t"])
        lines = []
        for e in ev[:9]:
            to = f"→{e['to']}" if e["to"] and e["to"] != e["from"] else ""
            if e["action"] == "WAIT":
                tail = e["detail"][:26]
            else:
                pb = "∞" if e["payback_h"] is None else f"{e['payback_h']:.2f}h"
                tail = f"save {e['saved_g']:.0f}g mig {e['migration_g']:.1f}g pb {pb}"
            lines.append(f"h{e['t']:>3} {e['action']:<6} {_short(e['job']):<5} {(e['from'] or '')[:7]:<7}{to[:8]:<8} {tail}")
        ax_txt.text(0.02, 0.66, "\n".join(lines) or "no MOVE / WAIT / REFUSE yet", transform=ax_txt.transAxes,
                    va="top", color=MUTED, fontsize=7.2, family="monospace")
        stamp = replay["timestamps"][t] if replay.get("timestamps") else ""
        title.set_text(f"{pol['name']}   ·   hour {t} / {T - 1}   {stamp}   ·   forecast: {pol['forecast']}")
        if progress and (t % 12 == 0 or t == T - 1):
            progress(f"frame {t + 1}/{T}")

    anim = animation.FuncAnimation(fig, draw, frames=T, interval=1000 / fps, blit=False)
    out: Dict[str, Optional[str]] = {"gif": None, "mp4": None}
    if out_gif:
        Path(out_gif).parent.mkdir(parents=True, exist_ok=True)
        anim.save(out_gif, writer=animation.PillowWriter(fps=fps), dpi=dpi, savefig_kwargs={"facecolor": BG})
        out["gif"] = str(out_gif)
    if out_mp4:
        if shutil.which("ffmpeg"):
            Path(out_mp4).parent.mkdir(parents=True, exist_ok=True)
            anim.save(out_mp4, writer=animation.FFMpegWriter(fps=fps, bitrate=2400), dpi=dpi,
                      savefig_kwargs={"facecolor": BG})
            out["mp4"] = str(out_mp4)
        elif progress:
            progress("ffmpeg not found: skipping MP4 (brew install ffmpeg / apt install ffmpeg)")
    plt.close(fig)
    return out


def _short(job_id: str) -> str:
    return job_id.replace("ml-", "M").replace("batch-", "B").replace("web-", "W")
