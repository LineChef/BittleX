#!/usr/bin/env python3
"""Draw the goal charts for the docs site from the goal journal (stdlib only; writes SVG files; reads nothing but the journal).

    python tools/gen_goal_charts.py [--journal ~/Desktop/G2Memory/goals/goal_journal.jsonl] [--out docs/assets/goals] [--goals ball_punt basket] [--check]

For each goal it writes five charts, named <goal>-<chart>.svg:
  success-by-session   the share of attempts that succeeded in each session, with the attempt count under each bar;
  score-per-attempt    every attempt's score and its running average (10 attempts); a change of scoring epoch starts a new line, because scores from two scoring rules are not comparable;
  outcomes             how the attempts ended, as counts of the scorer's outcome codes;
  success-by-setting   the success rate for each value of the goal's main setting (the basket's throw distance, the punt's distance), the dot's size the number of attempts;
  seconds-per-attempt  how long each session's attempts took (the median, with the shortest and longest).
Every file has a title and a text description, draws in light and dark (a media query inside the SVG), and carries only goal names, counts, scores and settings: no pictures, no text from the journal, nothing personal. A goal with too little data gets a chart that says so, so a page never links a missing file.
`--check` writes nothing and exits 1 when the files on disk differ from what the journal would draw (for a hook or a test). The journal is copied from the Pi by the review page's "Sync from the Pi" button, which also runs this.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import statistics
import sys
from collections import Counter, OrderedDict

DEFAULT_JOURNAL = os.path.expanduser("~/Desktop/G2Memory/goals/goal_journal.jsonl")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "assets", "goals")
GOALS = {"ball_punt": ("The ball punt", "punt_max_in", "the farthest he punts from, in inches"), "basket": ("The basket", "standoff_in", "the distance he throws from, in inches")}
W, H = 640, 320
STYLE = ("<style>.bg{fill:#fff}.ax{stroke:#8a8f98;stroke-width:1;fill:none}.gr{stroke:#e3e5e8;stroke-width:1}.tx{fill:#2b2f36;font:12px system-ui,sans-serif}.tt{fill:#2b2f36;font:600 14px system-ui,sans-serif}"
         ".sm{fill:#5b616b;font:11px system-ui,sans-serif}.b1{fill:#2f6fdb}.b2{fill:#d9822b}.b3{fill:#8a8f98}.ln{stroke:#d9822b;stroke-width:2;fill:none}.pt{fill:#2f6fdb;fill-opacity:.45}.ep{stroke:#8a8f98;stroke-dasharray:4 3}"
         "@media (prefers-color-scheme:dark){.bg{fill:#14171c}.ax{stroke:#7b818c}.gr{stroke:#2a2f37}.tx,.tt{fill:#e6e8eb}.sm{fill:#a2a8b2}.b1{fill:#6aa3ff}.b2{fill:#f0a35a}.pt{fill:#6aa3ff;fill-opacity:.5}.ln{stroke:#f0a35a}}</style>")


def read_rows(path: str) -> list[dict]:
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("{"):
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return rows


def attempts(rows: list[dict], goal: str) -> list[dict]:
    out = [r for r in rows if r.get("kind") == "attempt" and r.get("goal") == goal]
    out.sort(key=lambda r: r.get("time", ""))
    return out


def ok(a: dict) -> bool:
    return bool((a.get("outcome") or {}).get("success"))


def by_session(att: list[dict]) -> "OrderedDict[str, list[dict]]":
    d: OrderedDict = OrderedDict()
    for a in att:
        d.setdefault(a.get("session", "?"), []).append(a)
    return d


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def head(title: str, desc: str) -> list[str]:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">', f"<title id=\"t\">{esc(title)}</title>", f"<desc id=\"d\">{esc(desc)}</desc>", STYLE,
            f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>', f'<text class="tt" x="20" y="26">{esc(title)}</text>']


def empty(title: str, why: str) -> str:
    out = head(title, why) + [f'<text class="tx" x="{W // 2}" y="{H // 2}" text-anchor="middle">{esc(why)}</text>', "</svg>"]
    return "\n".join(out) + "\n"


def frame(out: list[str], ylabel: str, ymax: float, ticks: int = 4, fmt=lambda v: f"{v:g}") -> tuple:
    x0, x1, y0, y1 = 64, W - 20, H - 56, 52
    for i in range(ticks + 1):
        y = y0 - (y0 - y1) * i / ticks
        out.append(f'<line class="gr" x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}"/>')
        out.append(f'<text class="sm" x="{x0 - 6}" y="{y + 4:.1f}" text-anchor="end">{esc(fmt(ymax * i / ticks))}</text>')
    out.append(f'<line class="ax" x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}"/><line class="ax" x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}"/>')
    out.append(f'<text class="sm" x="16" y="{(y0 + y1) / 2:.0f}" transform="rotate(-90 16 {(y0 + y1) / 2:.0f})" text-anchor="middle">{esc(ylabel)}</text>')
    return x0, x1, y0, y1


def success_by_session(goal: str, att: list[dict]) -> str:
    name = GOALS[goal][0]
    title = f"{name}: success by session"
    sess = by_session(att)
    if len(sess) < 2:
        return empty(title, "Not enough sessions yet")
    items = list(sess.items())[-24:]
    rates = [sum(ok(a) for a in v) / len(v) for _k, v in items]
    desc = f"Bars, one per session, newest on the right: the share of attempts that succeeded. {len(items)} sessions, {sum(len(v) for _k, v in items)} attempts, success rates from {min(rates):.0%} to {max(rates):.0%}."
    out = head(title, desc)
    x0, x1, y0, y1 = frame(out, "attempts that succeeded", 1.0, 4, lambda v: f"{v:.0%}")
    bw = (x1 - x0) / len(items)
    for i, ((k, v), r) in enumerate(zip(items, rates)):
        h = (y0 - y1) * r
        x = x0 + i * bw + bw * 0.15
        out.append(f'<rect class="b1" x="{x:.1f}" y="{y0 - h:.1f}" width="{bw * 0.7:.1f}" height="{max(h, 0.5):.1f}"/>')
        out.append(f'<text class="sm" x="{x + bw * 0.35:.1f}" y="{y0 + 14}" text-anchor="middle">{len(v)}</text>')
    out.append(f'<text class="sm" x="{(x0 + x1) / 2:.0f}" y="{H - 14}" text-anchor="middle">sessions, oldest to newest (the number under a bar is its attempts)</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def running_mean(vals: list[float], window: int = 10) -> list[float]:
    return [sum(vals[max(0, i - window + 1):i + 1]) / len(vals[max(0, i - window + 1):i + 1]) for i in range(len(vals))]


def score_per_attempt(goal: str, att: list[dict]) -> str:
    name = GOALS[goal][0]
    title = f"{name}: score of every attempt"
    if len(att) < 5:
        return empty(title, "Not enough attempts yet")
    att = att[-300:]
    scores = [float((a.get("outcome") or {}).get("score") or 0.0) for a in att]
    epochs = [a.get("scoring_epoch") for a in att]
    desc = f"{len(att)} attempts in order, oldest left: each score from 0 to 1 as a dot, with a running average of 10. A dashed line shows a change of scoring rule; averages restart there."
    out = head(title, desc)
    x0, x1, y0, y1 = frame(out, "score (1 = success)", 1.0, 4, lambda v: f"{v:g}")
    n = len(att)

    def X(i):
        return x0 + (x1 - x0) * (i + 0.5) / n
    for i, s in enumerate(scores):
        out.append(f'<circle class="pt" cx="{X(i):.1f}" cy="{y0 - (y0 - y1) * s:.1f}" r="3"/>')
    seg_start = 0
    for i in range(1, n + 1):
        if i == n or epochs[i] != epochs[i - 1]:
            seg = scores[seg_start:i]
            pts = " ".join(f"{X(seg_start + j):.1f},{y0 - (y0 - y1) * m:.1f}" for j, m in enumerate(running_mean(seg)))
            if len(seg) > 1:
                out.append(f'<polyline class="ln" points="{pts}"/>')
            if i < n:
                out.append(f'<line class="ep" x1="{X(i) - (x1 - x0) / n / 2:.1f}" y1="{y1}" x2="{X(i) - (x1 - x0) / n / 2:.1f}" y2="{y0}"/>')
            seg_start = i
    out.append(f'<text class="sm" x="{(x0 + x1) / 2:.0f}" y="{H - 14}" text-anchor="middle">attempts, oldest to newest</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def outcomes(goal: str, att: list[dict]) -> str:
    name = GOALS[goal][0]
    title = f"{name}: how attempts ended"
    if len(att) < 3:
        return empty(title, "Not enough attempts yet")
    cnt = Counter((a.get("outcome") or {}).get("code") or "unknown" for a in att)
    items = cnt.most_common(10)
    desc = "Horizontal bars: the number of attempts for each outcome code. " + ", ".join(f"{k} {v}" for k, v in items) + "."
    out = head(title, desc)
    x0, x1 = 190, W - 40
    top = 48
    row = (H - top - 20) / len(items)
    mx = max(v for _k, v in items)
    good = {a.get("outcome", {}).get("code") for a in att if ok(a)}
    for i, (k, v) in enumerate(items):
        y = top + i * row
        w = (x1 - x0) * v / mx
        out.append(f'<text class="tx" x="{x0 - 8}" y="{y + row * 0.62:.1f}" text-anchor="end">{esc(k)}</text>')
        out.append(f'<rect class="{"b1" if k in good else "b3"}" x="{x0}" y="{y + row * 0.15:.1f}" width="{max(w, 1):.1f}" height="{row * 0.7:.1f}"/>')
        out.append(f'<text class="sm" x="{x0 + w + 6:.1f}" y="{y + row * 0.62:.1f}">{v}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def success_by_setting(goal: str, att: list[dict]) -> str:
    name, key, words = GOALS[goal]
    title = f"{name}: success by {key.replace('_', ' ')}"
    groups: dict = {}
    for a in att:
        v = (a.get("settings") or {}).get(key)
        if isinstance(v, (int, float)):
            g = groups.setdefault(float(v), [0, 0])
            g[1] += 1
            g[0] += 1 if ok(a) else 0
    if len(groups) < 2:
        return empty(title, "Not enough different settings tried yet")
    xs = sorted(groups)
    desc = f"Each dot is a value of the setting ({words}); height is the share of attempts that succeeded, size is how many attempts used it. Values from {xs[0]:g} to {xs[-1]:g}."
    out = head(title, desc)
    x0, x1, y0, y1 = frame(out, "attempts that succeeded", 1.0, 4, lambda v: f"{v:.0%}")
    lo, hi = xs[0], xs[-1]
    span = (hi - lo) or 1.0
    for v in xs:
        s, n = groups[v]
        cx = x0 + 20 + (x1 - x0 - 40) * (v - lo) / span
        cy = y0 - (y0 - y1) * s / n
        out.append(f'<circle class="b1" fill-opacity=".6" cx="{cx:.1f}" cy="{cy:.1f}" r="{min(4 + n ** 0.5 * 2, 16):.1f}"/>')
        out.append(f'<text class="sm" x="{cx:.1f}" y="{y0 + 14}" text-anchor="middle">{v:g}</text>')
        out.append(f'<text class="sm" x="{cx:.1f}" y="{cy - min(4 + n ** 0.5 * 2, 16) - 5:.1f}" text-anchor="middle">{n}</text>')
    out.append(f'<text class="sm" x="{(x0 + x1) / 2:.0f}" y="{H - 14}" text-anchor="middle">{esc(words)} (the number over a dot is its attempts)</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def seconds_per_attempt(goal: str, att: list[dict]) -> str:
    name = GOALS[goal][0]
    title = f"{name}: time per attempt"
    sess = [(k, [float(a["seconds"]) for a in v if isinstance(a.get("seconds"), (int, float))]) for k, v in by_session(att).items()]
    sess = [(k, v) for k, v in sess if v][-24:]
    if len(sess) < 2:
        return empty(title, "Not enough sessions yet")
    meds = [statistics.median(v) for _k, v in sess]
    ymax = max(max(v) for _k, v in sess)
    desc = f"For each of the last {len(sess)} sessions, the median seconds an attempt took (bar) and the shortest and longest (line). Medians from {min(meds):.0f} to {max(meds):.0f} seconds."
    out = head(title, desc)
    x0, x1, y0, y1 = frame(out, "seconds", ymax, 4, lambda v: f"{v:.0f}")
    bw = (x1 - x0) / len(sess)
    for i, ((_k, v), m) in enumerate(zip(sess, meds)):
        x = x0 + i * bw + bw * 0.15
        h = (y0 - y1) * m / ymax
        out.append(f'<rect class="b2" x="{x:.1f}" y="{y0 - h:.1f}" width="{bw * 0.7:.1f}" height="{max(h, 0.5):.1f}"/>')
        cx = x + bw * 0.35
        out.append(f'<line class="ax" x1="{cx:.1f}" y1="{y0 - (y0 - y1) * min(v) / ymax:.1f}" x2="{cx:.1f}" y2="{y0 - (y0 - y1) * max(v) / ymax:.1f}"/>')
    out.append(f'<text class="sm" x="{(x0 + x1) / 2:.0f}" y="{H - 14}" text-anchor="middle">sessions, oldest to newest</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


CHARTS = [("success-by-session", success_by_session), ("score-per-attempt", score_per_attempt), ("outcomes", outcomes), ("success-by-setting", success_by_setting), ("seconds-per-attempt", seconds_per_attempt)]


def render_all(rows: list[dict], goals: list[str]) -> dict:
    """{file name: svg text} for every chart of every goal."""
    files = {}
    for g in goals:
        att = attempts(rows, g)
        for name, fn in CHARTS:
            files[f"{g}-{name}.svg"] = fn(g, att)
    return files


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--journal", default=DEFAULT_JOURNAL)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--goals", nargs="*", default=list(GOALS))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    rows = read_rows(a.journal)
    if not rows:
        print(f"no journal at {a.journal}: charts not drawn")
        return 0 if not a.check else 1
    files = render_all(rows, a.goals)
    changed = []
    for name, text in files.items():
        p = os.path.join(a.out, name)
        old = open(p).read() if os.path.exists(p) else None
        if old != text:
            changed.append(name)
            if not a.check:
                os.makedirs(a.out, exist_ok=True)
                with open(p, "w") as f:
                    f.write(text)
    print(f"{len(files)} chart(s): {len(changed)} " + ("differ from the files on disk" if a.check else "written (the rest were already current)"))
    return 1 if (a.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
