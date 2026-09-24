import json

import pytest

from cao.carbon.sources.synthetic import generate_trace
from cao.replay.export import build_replay
from cao.replay.html import PLACEHOLDER, render_fragment, render_html
from cao.simulator import CarbonUnawarePolicy, MigrationAwarePolicy, generate_jobs, run_simulation

REGIONS = ["india", "sweden", "france"]
LAT = {r: {q: (10 if r == q else 120) for q in REGIONS} for r in REGIONS}


@pytest.fixture(scope="module")
def replay(cost_model):
    tr = {r: generate_trace(r, 30, 1) for r in REGIONS}
    jobs = generate_jobs(6, REGIONS, 30, seed=4)
    results = [run_simulation(tr, jobs, p, cost_model, LAT, record_timeline=True)
               for p in (CarbonUnawarePolicy(), MigrationAwarePolicy())]
    return build_replay(tr, jobs, results, cost_model), results


def test_export_shapes(replay):
    rep, results = replay
    T, n = rep["meta"]["hours"], rep["meta"]["n_jobs"]
    assert T == 30 and n == 6 and len(rep["policies"]) == 2
    for p in rep["policies"]:
        assert len(p["status"]) == T and all(len(row) == n for row in p["status"])
        assert all(s in (0, 1, 2, 3, 4) for row in p["status"] for s in row)
        assert all(a in (None, "M", "W", "H", "R") for row in p["action"] for a in row)
        totals = [c["total_g"] for c in p["cum"]]
        assert totals == sorted(totals)                       # cumulative carbon never decreases
        assert abs(totals[-1] - p["summary"]["total_g"]) < 0.2
        assert all(0 <= v <= 1 for row in p["progress"] for v in row)
    aware = rep["policies"][1]
    assert any(e["action"] in ("MOVE", "REFUSE", "WAIT") for e in aware["events"]) or aware["summary"]["migrations"] == 0
    assert rep["payback"]["sizes_gb"] and len(rep["payback"]["payback_h"]) == len(rep["payback"]["sizes_gb"])
    json.dumps(rep)  # serialisable


def test_status_transitions_consistent(replay):
    rep, _ = replay
    for p in rep["policies"]:
        for k in range(rep["meta"]["n_jobs"]):
            seq = [row[k] for row in p["status"]]
            # once done, stays done; never goes back to not-released
            first_done = next((i for i, s in enumerate(seq) if s == 4), None)
            if first_done is not None:
                assert all(s == 4 for s in seq[first_done:])
            first_rel = next((i for i, s in enumerate(seq) if s != 0), None)
            if first_rel is not None:
                assert all(s != 0 for s in seq[first_rel:])


def test_render_html_embeds_data(replay, tmp_path):
    rep, _ = replay
    out = render_html(rep, tmp_path / "replay.html")
    html = out.read_text()
    assert PLACEHOLDER not in html and '"policies"' in html and "<script>" in html
    assert "</script>" in html.split('"policies"')[-1]        # payload did not break out of the script tag


def test_render_gif(replay, tmp_path):
    pytest.importorskip("matplotlib")
    from cao.replay.animate import render_animation
    rep, _ = replay
    out = render_animation(rep, "migration-aware", tmp_path / "r.gif", None, fps=2, dpi=50, hours=3, progress=None)
    assert (tmp_path / "r.gif").stat().st_size > 1000 and out["gif"]


def test_render_fragment_has_no_document_wrapper(replay, tmp_path):
    rep, _ = replay
    frag = render_fragment(rep, tmp_path / "frag.html").read_text()
    assert frag.startswith("<title>") and "<html" not in frag and "<body" not in frag and "<!DOCTYPE" not in frag
    assert '"policies"' in frag and PLACEHOLDER not in frag
