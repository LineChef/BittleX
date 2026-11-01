"""The goal report the user reads to judge the learning (goals plan, "Reading the data"). Stdlib only, one self-contained HTML page.

    python -m pi_pipeline.goals report [GOAL] --html out.html     # from the journal and the learned state (pull them from the Pi first: g2goal pull)

Per goal: the success rate and mean score per session, what G2 has now against where he started, suggestions for the user's own settings, every change with its reason and the
attempts behind it, and each session's attempts. Settings sitting at the end of their range are flagged (a rule may be wrong, or the goal out of reach).
"""
from __future__ import annotations

import html

from .journal import Journal, State
from .spec import load


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


CSS = """
:root{--bg:#fbfbf9;--fg:#1d1d1b;--mut:#6b6b66;--line:#e2e1dc;--card:#fff;--good:#2f7d4f;--bad:#b3412e;--warn:#9a6a00;--bar:#4a7bb7;--bar2:#c9d6e8}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#161615;--fg:#ecebe6;--mut:#a3a29c;--line:#34332f;--card:#1f1f1d;--good:#6cc08c;--bad:#e47a66;--warn:#e0b44c;--bar:#7aa6dc;--bar2:#2f3f55}}
:root[data-theme="dark"]{--bg:#161615;--fg:#ecebe6;--mut:#a3a29c;--line:#34332f;--card:#1f1f1d;--good:#6cc08c;--bad:#e47a66;--warn:#e0b44c;--bar:#7aa6dc;--bar2:#2f3f55}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:960px;margin:0 auto;padding:20px 16px 60px}h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px}h3{font-size:15px;margin:16px 0 6px}
.mut{color:var(--mut)}.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:22px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600}ul{padding-left:20px}li{margin:4px 0}details summary{cursor:pointer;color:var(--mut)}code{font-size:13px}
.tag{display:inline-block;font-size:12px;padding:1px 7px;border-radius:9px;border:1px solid var(--line);color:var(--mut)}
"""

ACTION_WORD = {"try": "trying", "kept": "kept", "undo": "undone", "suggest": "suggestion", "keep": "same again", "none": "no change", "not_counted": "not counted"}


def _curve(sessions: list[dict]) -> str:
    """Bars: success rate per session; a dot: mean score. Inline SVG."""
    pts = []
    for s in sessions:
        sc = [a["outcome"]["score"] for a in s["attempts"] if a["outcome"].get("score") is not None]
        ok = sum(1 for a in s["attempts"] if a["outcome"].get("success"))
        pts.append((len(sc), ok, (sum(sc) / len(sc)) if sc else None))
    if not pts:
        return ""
    w, h, pad = max(240, 46 * len(pts)), 150, 24
    bw = (w - pad) / len(pts)
    parts = [f'<svg viewBox="0 0 {w} {h + 30}" width="100%" style="max-width:{w}px" role="img" aria-label="success rate per session">',
             f'<line x1="{pad}" y1="{h}" x2="{w}" y2="{h}" stroke="var(--line)"/>',
             f'<text x="0" y="12" font-size="11" fill="var(--mut)">100%</text><text x="0" y="{h}" font-size="11" fill="var(--mut)">0</text>']
    for i, (n, ok, mean) in enumerate(pts):
        x = pad + i * bw + bw * 0.15
        rate = ok / n if n else 0.0
        bh = rate * (h - 16)
        parts.append(f'<rect x="{x:.1f}" y="{h - bh:.1f}" width="{bw * 0.7:.1f}" height="{bh:.1f}" rx="3" fill="var(--bar)"><title>session {i + 1}: {ok} of {n} succeeded</title></rect>')
        if mean is not None:
            parts.append(f'<circle cx="{x + bw * 0.35:.1f}" cy="{h - mean * (h - 16):.1f}" r="4" fill="var(--fg)"><title>mean score {mean:.2f}</title></circle>')
        parts.append(f'<text x="{x + bw * 0.35:.1f}" y="{h + 16}" font-size="11" text-anchor="middle" fill="var(--mut)">{i + 1}</text>')
        parts.append(f'<text x="{x + bw * 0.35:.1f}" y="{h + 28}" font-size="10" text-anchor="middle" fill="var(--mut)">{ok}/{n}</text>')
    parts.append("</svg>")
    return "".join(parts) + '<p class="mut">Bars: share of counted attempts that succeeded, per session (number under each). Dots: mean score (0 to 1).</p>'


def _knobs_for(goal):
    from .approach import make
    try:
        return {k.name: k for k in goal.knobs(make(goal.approach).knobs())}
    except Exception:  # noqa: BLE001
        return {}


def goal_page(goal_id: str, journal: Journal | None = None, state: State | None = None) -> str:
    goals, _problems = load()
    goal = goals.get(goal_id)
    title = goal.title if goal else goal_id
    journal = journal or Journal()
    state = state or State()
    sessions = journal.sessions(goal_id)
    knobs = _knobs_for(goal) if goal else {}
    from . import overrides as ovr
    overrides_data = ovr.load()
    out = [f"<h1>{_e(title)}</h1><p class=mut>Goal <code>{_e(goal_id)}</code>: what G2 tried, what he changed and why. Built from the goal journal; nothing here is a Claude call.</p>"]
    attempts = [a for s in sessions for a in s["attempts"]]
    counted = [a for a in attempts if a["outcome"].get("score") is not None]
    ok = sum(1 for a in counted if a["outcome"].get("success"))
    decisions = [d for s in sessions for d in s["decisions"]]
    all_rows = journal.read()
    verdicts = {}
    for r in all_rows:
        if r.get("kind") == "verdict" and r.get("goal") == goal_id:
            verdicts[(r.get("session"), r.get("index"))] = r.get("verdict")
    n_right = sum(1 for v in verdicts.values() if v == "right")
    n_wrong = sum(1 for v in verdicts.values() if v == "wrong")
    kept = sum(1 for d in decisions if d.get("action") == "kept")
    undone = sum(1 for d in decisions if d.get("action") == "undo")
    out.append("<div class=tiles>" + "".join(f"<div class=tile><span class=mut>{_e(k)}</span><b>{_e(v)}</b></div>" for k, v in (
        ("sessions", len(sessions)), ("counted attempts", len(counted)), ("succeeded", f"{ok} of {len(counted)}"), ("changes kept", kept), ("changes undone", undone),
        ("your verdicts", f"{n_right} right, {n_wrong} wrong" if verdicts else "none yet"))) + "</div>")
    if not sessions:
        out.append("<p>No sessions yet.</p>")
        return _page(title, "".join(out))
    out.append("<h2>Learning curve</h2>" + _curve(sessions))

    # what he has now, per conditions
    for cond_key, st in (state.data.get(goal_id) or {}).items():
        first = next((s["start"]["settings"] for s in sessions if _cond_key(s["start"]) == cond_key), {})
        last = next((s["end"]["settings_now"] for s in reversed(sessions) if s["end"] and _cond_key(s["start"]) == cond_key), None) or first
        rows = []
        for name, now in last.items():
            k = knobs.get(name)
            if k is None:
                continue
            start = first.get(name)
            edge = ""
            if k.kind in ("float", "int") and k.control == "free" and ((k.lo is not None and float(now) <= k.lo) or (k.hi is not None and float(now) >= k.hi)):
                edge = ' <span class="warn">at the end of its range</span>'
            changed = start != now
            rows.append(f"<tr><td>{_e(name)}</td><td><span class=tag>{_e(k.control)}</span></td><td>{_e(k.show(start) if start is not None else '')}</td>"
                        f"<td>{'<b>' if changed else ''}{_e(k.show(now))}{'</b>' if changed else ''}{edge}</td></tr>")
        from . import overrides as ovr
        ov = ovr.for_conditions(goal_id, cond_key, overrides_data)
        focus = st.get("focus")
        trial = f"<p>Working on: <b>{_e(focus)}</b> (the setting his recent failures point at most).</p>" if focus else ""
        mine = [f"<li>{_e(x)}</li>" for x in ovr.describe(goal_id, overrides_data)]
        out.append(f"<h2>Settings now <span class=mut>({_e(cond_key)}, {st.get('count', 0)} attempts)</span></h2>{trial}"
                   "<div class=scroll><table><tr><th>setting</th><th>who changes it</th><th>first session</th><th>now</th></tr>" + "".join(rows) + "</table></div>"
                   + (f"<h3>Your overrides</h3><ul>{''.join(mine)}</ul>" if mine else ""))
        recs = []
        for name, vals in (st.get("values") or {}).items():
            k = knobs.get(name)
            tried = sorted((r for r in vals.values() if r.get("n")), key=lambda r: (str(type(r["v"])), r["v"]))
            if k is None or not tried:
                continue
            nowv = last.get(name)
            cells = []
            for r in tried:
                here = " <b>&larr; now</b>" if r["v"] == nowv else ""
                ban = " <span class=bad>undone by you</span>" if str(r["v"]) in ((ov.get("banned") or {}).get(name) or {}) or _vk(r["v"]) in ((ov.get("banned") or {}).get(name) or {}) else ""
                votes = f", misses say lower {r['down']} / higher {r['up']}" if (r.get("down") or r.get("up")) else ""
                cells.append(f"{_e(k.show(r['v']))}: {r['hits']} of {r['n']} good{votes}{here}{ban}")
            recs.append(f"<tr><td>{_e(name)}</td><td>{'<br>'.join(cells)}</td></tr>")
        if recs:
            out.append("<h3>The record behind each setting</h3><p class=mut>Every attempt counts for the value in use, judged by its own stage (search, walking up, lining up, the punch). "
                       "He keeps the value with the best record over at least 2 attempts.</p><div class=scroll><table><tr><th>setting</th><th>values tried</th></tr>" + "".join(recs) + "</table></div>")
        sug = st.get("suggestions") or {}
        if sug:
            out.append("<h3>Suggestions for you (settings only you change)</h3><ul>" + "".join(
                f"<li><span class=tag>{_e({'new': 'not asked yet', 'later': 'for you to review'}.get(v.get('status', 'new'), v.get('status')))}</span> <b>{_e(n)}</b> {_e(v.get('old'))} &rarr; {_e(v.get('new'))}: {_e(v.get('because'))} "
                f"<span class=mut>(attempt {', '.join(map(str, v.get('evidence', [])))}; <code>g2goal confirm {_e(goal_id)} {_e(n)}</code> or cancel)</span></li>" for n, v in sug.items()) + "</ul>")

    # every change
    ch = [d for d in decisions if d.get("action") in ("kept", "undo", "suggest")]
    yours = [r for r in journal.read() if r.get("kind") == "override" and r.get("goal") == goal_id]
    if yours:
        out.append("<h2>Your overrides, in order</h2><ul>" + "".join(f"<li>{_e(r.get('time'))}: {_e(r.get('detail'))}</li>" for r in yours) + "</ul>")
    if ch:
        out.append("<h2>What he kept, undid and suggested</h2><p class=mut>The values he tried along the way are in each session's notes below.</p><ul>" + "".join(
            f"<li><span class=tag>{_e(ACTION_WORD.get(d['action'], d['action']))}</span> {_e(d.get('note'))} <span class=mut>(attempts {', '.join(map(str, d.get('evidence') or []))})</span></li>" for d in ch) + "</ul>")

    # sessions, newest first
    out.append("<h2>Sessions</h2>")
    for idx, s in reversed(list(enumerate(sessions, 1))):
        st0 = s["start"]
        end = s["end"] or {}
        head = f"{_e(str(st0.get('mode')).capitalize()) if st0.get('mode') else 'Session'} {idx}: {_e(st0.get('time'))}, {_e(_cond_key(st0))}; ended: {_e(end.get('why', 'did not finish'))}; {end.get('successes', '?')} of {end.get('attempts', '?')} succeeded"
        rows = []
        for a in s["attempts"]:
            o = a["outcome"]
            cls = "good" if o.get("success") else ("mut" if o.get("score") is None else "bad")
            diff = ", ".join(f"{k}={v}" for k, v in a["settings"].items() if st0["settings"].get(k) != v)
            nums = a.get("numbers") or {}
            v = verdicts.get((a.get("session"), a.get("index")))
            vcell = f"<span class={'good' if v == 'right' else 'bad'}>{_e(v)}</span>" if v else (f"<code>g2goal verdict {_e(goal_id)} {a['number']} right|wrong</code>" if a.get("number") else "")
            rows.append(f"<tr><td>{_e(a.get('number') or '')}</td><td class={cls}>{_e(o.get('code'))}</td><td>{'' if o.get('score') is None else format(o['score'], '.2f')}</td><td>{_e(o.get('text'))}</td>"
                        f"<td>{_e(nums.get('found_by') or '')}</td><td>{_e('' if a.get('pack_pct') is None else str(a['pack_pct']) + '%')}</td><td>{_e(diff)}</td><td>{vcell}</td></tr>")
        notes = "".join(f"<li><span class=tag>{_e(ACTION_WORD.get(d['action'], d['action']))}</span> {_e(d.get('note'))}</li>" for d in s["decisions"])
        lessons = "".join(f"<li>{_e(x)}</li>" for x in end.get("lessons") or [])
        body = ("<div class=scroll><table><tr><th>#</th><th>result</th><th>score</th><th>what happened</th><th>found by</th><th>pack</th><th>settings changed this session</th><th>your verdict</th></tr>"
                + "".join(rows) + "</table></div>" + (f"<h3>His notes after each attempt</h3><ul>{notes}</ul>" if notes else "")
                + (f"<h3>Saved to memory</h3><ul>{lessons}</ul>" if lessons else ""))
        out.append(f"<details class=card {'open' if idx == len(sessions) else ''}><summary>{head}</summary>{body}</details>")

    out.append("<h2>What to look for</h2><ul><li>Does the success rate rise across sessions on the same floor?</li><li>Does the record for the setting he works on settle on one value?</li><li>Do the values he keeps hold their record in the next session?</li>"
               "<li>Do the notes match what you saw?</li><li>Is a setting creeping to the end of its range (flagged above)?</li>"
               "<li>Ten attempts is a small sample: a change kept on 2 or 3 attempts can be luck.</li></ul>")
    return _page(title, "".join(out))


def _vk(v) -> str:
    from .judge import vkey
    return vkey(v)


def _cond_key(start: dict) -> str:
    c = start.get("conditions") or {}
    return "|".join(f"{k}={c[k]}" for k in sorted(c))


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{_e(title)} goal</title>"
            f"<style>{CSS}</style></head><body><main>{body}</main></body></html>")


def text_history(goal_id: str, journal: Journal | None = None, last: int = 3) -> str:
    """The same data as text, for `g2goal history` on the Pi."""
    journal = journal or Journal()
    sessions = journal.sessions(goal_id)[-last:]
    if not sessions:
        return f"{goal_id}: no sessions yet"
    lines = []
    for s in sessions:
        end = s["end"] or {}
        lines.append(f"session {s['start']['time']} ({_cond_key(s['start'])}): ended {end.get('why', '?')}, {end.get('successes', '?')} of {end.get('attempts', '?')} succeeded")
        for a in s["attempts"]:
            o = a["outcome"]
            lines.append(f"  {a['index']:>2}  {o.get('code', ''):16s} {'' if o.get('score') is None else format(o['score'], '.2f'):5s} {o.get('text', '')}")
        for d in s["decisions"]:
            if d.get("action") in ("try", "kept", "undo", "suggest"):
                lines.append(f"      -> {d.get('note')}")
    return "\n".join(lines)
