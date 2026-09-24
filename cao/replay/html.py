"""Render the self-contained replay page: template + embedded JSON, opens from file://."""
from __future__ import annotations

import json
from pathlib import Path

PLACEHOLDER = "/*__REPLAY_DATA__*/null"


def render_html(replay: dict, out_path) -> Path:
    template = (Path(__file__).parent / "template.html").read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise RuntimeError("template placeholder missing")
    payload = json.dumps(replay, separators=(",", ":")).replace("</", "<\\/")
    html = template.replace(PLACEHOLDER, payload)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def render_fragment(replay: dict, out_path) -> Path:
    """Same page as render_html() without the document wrapper (title + style + body content),
    for hosts that wrap the file in their own skeleton (e.g. the claude.ai Artifact viewer)."""
    import re

    full = render_html(replay, out_path)
    html = full.read_text(encoding="utf-8")
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    head = re.sub(r"<meta[^>]*>\s*", "", head)
    full.write_text(head.strip() + "\n" + body.strip() + "\n", encoding="utf-8")
    return full
