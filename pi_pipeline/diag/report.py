"""One report per session: everything G2 logged while a session ran, in one place (text, or a self-contained HTML page).

    python -m pi_pipeline.diag report [SESSION | --kind explore] [--html out.html]

A session's own diagnostics folder (`events.jsonl`, `manifest.json`, `profile.txt`) gives its time window; the other logs are read for that window:

  * walks          the walk auto-logs (`telemetry/autolog.py` sidecars): how each ended, late ticks, worst tick gap, floor label
  * behaviour      mode changes and reflexes (the DIAG effects, `behavior/diag_bridge.py` names)
  * speech         `narration timing:` / `narration dropped` lines (behavior/narrator.py) and the walks that did not stop in time
  * wake word      the wake-trigger log (`voice/wake_log.py`): triggers, ones the gates ignored, ones that looked false
  * API            billed Claude calls in the window (`voice/api_log.py`)
  * camera/workers camera timeouts and supervised-worker restarts (`util/supervisor.py`)
  * problems       every WARN or worse event, in time order
  * profile        the sampling profiler's report when the session ran with `G2_PROFILE=1`

  * checks         the numbers the 2026-10-18 fixes are meant to move, each marked ok / CHECK against its target (`checks()`), with the floor label of the walks
                   (a walk with no floor label cannot feed the body fits, tools/g2_ingest.py)

An exploration writes its own report when it ends (`write_after()`: `report.txt` and `report.html` in the session folder, or `explore_HHMMSS.*` for a session run inside
the voice service, whose time window is passed in); `tools/g2_explore.sh report` shows the latest one.

Read-only apart from those two files; nothing is sent anywhere. Each section is best-effort: a missing log just leaves its section empty.
"""
from __future__ import annotations

import html
import json
import re
import statistics
import time
from datetime import datetime
from pathlib import Path

from .core import _LEVELS, _read_events, _resolve_session

_NARR = re.compile(r"narration timing: queued ([\d.]+) s, synthesis ([\d.]+) s, play ([\d.]+) s.*?, ([\d.]+) s from decision to end")
_NARR_OLD = re.compile(r"narration timing: queued ([\d.]+) s, speech call ([\d.]+) s")
_CAMERA = re.compile(r"camera (isn't answering|timed out|timeout)|did not answer|snapshot timed out", re.I)


def _window(d: Path, evs: list[dict]) -> tuple[float, float]:
    man = {}
    try:
        man = json.loads((d / "manifest.json").read_text())
    except (OSError, ValueError):
        pass
    t0 = man.get("started_wall") or (evs[0]["wall_ts"] if evs else 0.0)
    t1 = man.get("ended_wall") or (evs[-1]["wall_ts"] if evs else t0)
    return float(t0), float(t1)


def _ts(s: str, fmt: str) -> float | None:
    try:
        return time.mktime(time.strptime(s, fmt))
    except (TypeError, ValueError):
        return None


def _walks(t0: float, t1: float) -> list[dict]:
    try:
        from ..telemetry.autolog import base_dir
        root = base_dir()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for day in {datetime.fromtimestamp(t0).strftime("%Y%m%d"), datetime.fromtimestamp(t1).strftime("%Y%m%d")}:
        for side in sorted((root / day).glob("*.json")) if (root / day).is_dir() else []:
            if side.name.endswith(".labels.json"):
                continue
            try:
                m = json.loads(side.read_text())
            except (OSError, ValueError):
                continue
            st = _ts(m.get("started"), "%Y-%m-%dT%H:%M:%S")
            if st is not None and t0 - 1 <= st <= t1 + 1:
                out.append(dict(m, run=side.stem))
    return sorted(out, key=lambda m: m.get("started") or "")


def _jsonl_rows(path, t0: float, t1: float, key: str, fmt: str) -> list[dict]:
    if path is None or not Path(path).exists():
        return []
    out = []
    for line in Path(path).read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        t = _ts(r.get(key), fmt)
        if t is not None and t0 - 1 <= t <= t1 + 1:
            out.append(r)
    return out


def latest_of_kind(kind: str) -> str | None:
    """The newest session folder whose manifest says it was started as `kind` ("explore", "voice", ...), or None."""
    from .core import _sessions
    for d in reversed(_sessions()):
        try:
            if json.loads((d / "manifest.json").read_text()).get("subsystem_hint") == kind:
                return str(d)
        except (OSError, ValueError):
            continue
    return None


def build(session: str | None = None, since: float | None = None, until: float | None = None) -> dict | None:
    """Every section as plain data (lists and numbers), or None when there is no such session. `since` / `until` (wall-clock seconds) narrow the window to part of a
    long session, for an exploration run inside the voice service."""
    d = _resolve_session(session)
    if d is None:
        return None
    evs = list(_read_events(d))
    t0, t1 = _window(d, evs)
    if since is not None or until is not None:
        t0, t1 = (t0 if since is None else float(since)), (t1 if until is None else float(until))
        evs = [e for e in evs if t0 - 1 <= e.get("wall_ts", t0) <= t1 + 1]
    man = {}
    try:
        man = json.loads((d / "manifest.json").read_text())
    except (OSError, ValueError):
        pass
    msgs = [(e, str(e.get("msg", ""))) for e in evs if e.get("name") == "log"]
    rep: dict = {"session": d.name, "kind": man.get("subsystem_hint"), "git": (man.get("git") or {}).get("sha"), "started": time.strftime("%Y-%m-%d %I:%M:%S %p", time.localtime(t0)),
                 "duration_s": round(t1 - t0, 1), "clean_exit": man.get("clean_exit")}

    walks = _walks(t0, t1)
    lates = [w["late_ticks_pct"] for w in walks if w.get("late_ticks_pct") is not None]
    rep["walks"] = {"count": len(walks), "end_reasons": _count(w.get("end_reason") or "unfinished" for w in walks),
                    "falls": sum(1 for w in walks if w.get("end_reason") == "fall"), "late_ticks_pct_median": _median(lates), "late_ticks_pct_max": max(lates) if lates else None,
                    "worst_tick_gap_ms": max((w["worst_tick_gap_ms"] for w in walks if w.get("worst_tick_gap_ms") is not None), default=None),
                    "floors": _count(w.get("surface") or "unknown" for w in walks),
                    "rows": [{k: w.get(k) for k in ("run", "started", "end_reason", "duration_s", "late_ticks_pct", "worst_tick_gap_ms", "surface", "foot_trim")} for w in walks]}

    beh = [e for e in evs if e.get("sub") == "behavior" and e.get("name") != "log"]
    rep["behavior"] = {"events": _count(e["name"] for e in beh), "reflexes": [_line(e) for e in beh if _LEVELS.get(e.get("lvl", "INFO"), 20) >= 30][-20:]}

    timing, old, dropped = [], [], []
    for _e, m in msgs:
        if (g := _NARR.search(m)):
            timing.append(tuple(float(x) for x in g.groups()))
        elif (g := _NARR_OLD.search(m)):
            old.append(float(g.group(1)) + float(g.group(2)))
        elif m.startswith("narration dropped"):
            dropped.append(m)
    totals = [x[3] for x in timing] + old
    rep["speech"] = {"lines": len(totals), "dropped": len(dropped), "decision_to_end_median_s": _median(totals), "decision_to_end_max_s": max(totals) if totals else None,
                     "synthesis_median_s": _median([x[1] for x in timing]), "queue_median_s": _median([x[0] for x in timing]),
                     "dropped_lines": dropped[-8:],
                     "walk_stop_timeouts": sum(1 for _e, m in msgs if "did not stop within" in m),
                     "slow_walk_ends": sum(1 for e in evs if e.get("name") == "walk.slow_end")}

    try:
        from ..voice import wake_log
        wrows = _jsonl_rows(wake_log._path(), t0, t1, "t", "%Y-%m-%dT%H:%M:%S")
        trig = [r for r in wrows if r.get("type") == "trigger"]
        pairs = wake_log.pairs(wrows)
        rep["wake"] = {"triggers": len(trig), "ignored_by_gates": sum(1 for r in trig if r.get("ignored")),
                       "looked_false": sum(1 for _t, o in pairs if o is not None and wake_log.looks_false(o)),
                       "looked_real": sum(1 for _t, o in pairs if o is not None and not wake_log.looks_false(o))}
    except Exception:  # noqa: BLE001
        rep["wake"] = {}

    try:
        from ..voice import api_log
        arows = _jsonl_rows(api_log.log_path(), t0, t1, "ts", "%Y-%m-%d %H:%M:%S")
        rep["api"] = {"billed_calls": sum(1 for r in arows if r.get("event") == "start" and r.get("api") != "models.list"),
                      "errors": sum(1 for r in arows if r.get("event") == "error"),
                      "summary": api_log.summarize([json.dumps(r) for r in arows], hours=1e6, now=t1 + 2) if arows else "none in this session"}
    except Exception:  # noqa: BLE001
        rep["api"] = {}

    rep["camera"] = {"timeouts": sum(1 for _e, m in msgs if _CAMERA.search(m)),
                     "worker_restarts": _count(e.get("worker", "?") for e in evs if e.get("name") == "worker.restart"),
                     "workers_gave_up": [e.get("worker") for e in evs if e.get("name") == "worker.gave_up"]}
    rep["problems"] = [_line(e) for e in evs if _LEVELS.get(e.get("lvl", "INFO"), 20) >= 30][-60:]
    prof = d / "profile.txt"
    rep["profile"] = prof.read_text()[:6000] if prof.exists() else None
    rep["checks"] = checks(rep)
    return rep


# targets for the checks: what the 2026-10-18 fixes are meant to reach (STATUS "Open problems" has the numbers they started from)
MAX_LATE_TICKS_PCT = 5.0            # was 30 to 32% in the 2026-10-18 explorations
MAX_SPEECH_S = 8.0                  # the narrator's own late limit; was 7 to 17 s
UNKNOWN_FLOORS = ("unknown", "", None)


def checks(rep: dict) -> list[tuple[str, bool | None, str]]:
    """(name, ok, detail) for the numbers a roam is read for. ok is None when the session has nothing to judge it by."""
    w, s, c, wk = rep["walks"], rep["speech"], rep["camera"], rep.get("wake") or {}
    out: list[tuple[str, bool | None, str]] = []
    out.append(("no falls", w["falls"] == 0 if w["count"] else None, f"{w['falls']} of {w['count']} walks ended in a fall"))
    lt = w["late_ticks_pct_median"]
    out.append((f"late walk ticks under {MAX_LATE_TICKS_PCT:g}%", None if lt is None else lt <= MAX_LATE_TICKS_PCT, f"median {_fmt(lt)}%, max {_fmt(w['late_ticks_pct_max'])}%"))
    out.append(("camera answered every time", c["timeouts"] == 0, f"{c['timeouts']} timeouts"))
    sp = s["decision_to_end_max_s"]
    out.append((f"speech within {MAX_SPEECH_S:g} s, none dropped", None if sp is None else (sp <= MAX_SPEECH_S and s["dropped"] == 0), f"max {_fmt(sp)} s, {s['dropped']} dropped of {s['lines']} lines"))
    out.append(("walks stop when told", s["walk_stop_timeouts"] == 0 and s["slow_walk_ends"] == 0, f"{s['walk_stop_timeouts']} did not stop in 5 s, {s['slow_walk_ends']} slow ends"))
    out.append(("no false wake triggers", None if not wk else wk.get("looked_false", 0) == 0, f"{_fmt(wk.get('looked_false'))} looked false of {_fmt(wk.get('triggers'))} triggers"))
    out.append(("no worker gave up", not c["workers_gave_up"], ", ".join(map(str, c["workers_gave_up"])) or "none"))
    unlabeled = sum(n for k, n in w["floors"].items() if k in UNKNOWN_FLOORS)
    out.append(("every walk had a floor label", None if not w["count"] else unlabeled == 0, f"floors {_fmt(w['floors'])}"))
    return out


def headline(rep: dict) -> str:
    """One line for a log: how many checks failed and which."""
    bad = [n for n, ok, _d in rep.get("checks", []) if ok is False]
    return f"session report: {len(rep.get('checks', [])) - len(bad)} of {len(rep.get('checks', []))} checks ok" + (f"; CHECK: {', '.join(bad)}" if bad else "")


def write_after(session: str | None = None, since: float | None = None, until: float | None = None, name: str = "report") -> str | None:
    """Build the report and save `<name>.txt` and `<name>.html` in the session folder. Returns the text, or None when there is nothing to report. Never raises."""
    try:
        d = _resolve_session(session)
        rep = build(session, since, until)
        if d is None or rep is None:
            return None
        text = to_text(rep)
        (d / f"{name}.txt").write_text(text + "\n")
        (d / f"{name}.html").write_text(to_html(rep))
        return text
    except Exception:  # noqa: BLE001 -- a report must never disturb the session it describes
        return None


def _count(it) -> dict:
    out: dict = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def _line(e: dict) -> str:
    t = time.strftime("%I:%M:%S %p", time.localtime(e.get("wall_ts", 0)))
    kv = " ".join(f"{k}={v}" for k, v in e.items() if k not in ("wall_ts", "mono_t", "sid", "sub", "lvl", "name"))
    return f"{t} {e.get('lvl', '?')} {e.get('sub', '?')}/{e.get('name', '?')} {kv}"[:300]


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, dict):
        return ", ".join(f"{k} {n}" for k, n in v.items()) or "none"
    return str(v)


def to_text(rep: dict) -> str:
    w, s, wk, a, c = rep["walks"], rep["speech"], rep.get("wake") or {}, rep.get("api") or {}, rep["camera"]
    L = [f"session {rep['session']} ({rep['kind']})  started {rep['started']}  {rep['duration_s'] / 60:.1f} min  clean exit {_fmt(rep['clean_exit'])}  git {str(rep['git'])[:10]}",
         f"walks: {w['count']} ({_fmt(w['end_reasons'])}); falls {w['falls']}; late ticks median {_fmt(w['late_ticks_pct_median'])}% max {_fmt(w['late_ticks_pct_max'])}%; "
         f"worst tick gap {_fmt(w['worst_tick_gap_ms'])} ms; floors {_fmt(w['floors'])}",
         f"behaviour: {_fmt(rep['behavior']['events'])}",
         f"speech: {s['lines']} narration lines, {s['dropped']} dropped; decision to end median {_fmt(s['decision_to_end_median_s'])} s, max {_fmt(s['decision_to_end_max_s'])} s "
         f"(synthesis median {_fmt(s['synthesis_median_s'])} s); walks that did not stop in 5 s: {s['walk_stop_timeouts']}; slow walk ends: {s['slow_walk_ends']}",
         f"wake word: {_fmt(wk.get('triggers'))} triggers, {_fmt(wk.get('ignored_by_gates'))} ignored by the gates, {_fmt(wk.get('looked_real'))} looked real, {_fmt(wk.get('looked_false'))} looked false",
         f"API: {_fmt(a.get('billed_calls'))} billed calls, {_fmt(a.get('errors'))} errors",
         f"camera: {c['timeouts']} timeouts; worker restarts {_fmt(c['worker_restarts'])}" + (f"; GAVE UP: {', '.join(map(str, c['workers_gave_up']))}" if c["workers_gave_up"] else "")]
    if rep.get("checks"):
        L.append("checks (" + headline(rep).split(": ", 1)[1].split(";")[0] + "):")
        L += [f"  [{'ok' if ok else 'CHECK' if ok is False else '--'}] {n}: {d}" for n, ok, d in rep["checks"]]
    if rep["problems"]:
        L.append("problems (WARN and worse):")
        L += [f"  {p}" for p in rep["problems"][-25:]]
    if rep["profile"]:
        L.append("profile.txt is in the session folder (G2_PROFILE=1)")
    return "\n".join(L)


_CSS = """:root{--bg:#fbfbfa;--fg:#1d1d1b;--mut:#6b6b66;--line:#e3e2de;--bad:#b3261e;--ok:#2e7d32;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe7;--mut:#a3a29c;--line:#34332f;--bad:#f2b8b5;--ok:#a5d6a7;--card:#1f1f1d}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:980px;margin-inline:auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}.mut{color:var(--mut)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}.tile b{display:block;font-size:20px}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
pre{white-space:pre-wrap;font-size:12px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;overflow-x:auto}.bad{color:var(--bad)}"""


def to_html(rep: dict) -> str:
    e = html.escape
    w, s, wk, a, c = rep["walks"], rep["speech"], rep.get("wake") or {}, rep.get("api") or {}, rep["camera"]
    tiles = [("walks", w["count"]), ("falls", w["falls"]), ("late ticks (median %)", w["late_ticks_pct_median"]), ("speech lag (median s)", s["decision_to_end_median_s"]),
             ("narration dropped", s["dropped"]), ("wake: looked false", wk.get("looked_false")), ("billed API calls", a.get("billed_calls")), ("camera timeouts", c["timeouts"])]
    out = [f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>G2 session report</title><style>{_CSS}</style></head><body>",
           f"<h1>G2 session {e(rep['session'])}</h1><div class=mut>{e(str(rep['kind']))} · started {e(rep['started'])} · {rep['duration_s'] / 60:.1f} min · clean exit {e(_fmt(rep['clean_exit']))} · git {e(str(rep['git'])[:10])}</div>",
           "<div class=tiles>" + "".join(f"<div class=tile><span class=mut>{e(k)}</span><b>{e(_fmt(v))}</b></div>" for k, v in tiles) + "</div>",
           "<h2>Checks</h2><table>" + "".join(
               f"<tr><td class={'bad' if ok is False else ''}>{'ok' if ok else 'CHECK' if ok is False else '--'}</td><td>{e(n)}</td><td class=mut>{e(d)}</td></tr>" for n, ok, d in rep.get("checks", [])) + "</table>",
           "<h2>Walks</h2>"]
    if w["rows"]:
        cols = ["run", "started", "end_reason", "duration_s", "late_ticks_pct", "worst_tick_gap_ms", "surface", "foot_trim"]
        out.append("<table><tr>" + "".join(f"<th>{c_}</th>" for c_ in cols) + "</tr>" + "".join(
            "<tr>" + "".join(f"<td class={'bad' if k == 'end_reason' and r.get(k) == 'fall' else ''}>{e(_fmt(r.get(k)))}</td>" for k in cols) + "</tr>" for r in w["rows"]) + "</table>")
    else:
        out.append("<p class=mut>no walks logged in this session</p>")
    out += [f"<h2>Speech</h2><p>{s['lines']} narration lines, {s['dropped']} dropped as late. Decision to end of speech: median {e(_fmt(s['decision_to_end_median_s']))} s, max {e(_fmt(s['decision_to_end_max_s']))} s; "
            f"synthesis median {e(_fmt(s['synthesis_median_s']))} s; queue median {e(_fmt(s['queue_median_s']))} s. Walks that did not stop within 5 s: {s['walk_stop_timeouts']}; slow walk ends: {s['slow_walk_ends']}.</p>",
            f"<h2>Wake word</h2><p>{e(_fmt(wk.get('triggers')))} triggers, {e(_fmt(wk.get('ignored_by_gates')))} ignored by the gates, {e(_fmt(wk.get('looked_real')))} looked real, {e(_fmt(wk.get('looked_false')))} looked false.</p>",
            f"<h2>Behaviour</h2><p>{e(_fmt(rep['behavior']['events']))}</p>",
            f"<h2>API</h2><pre>{e(str(a.get('summary', '-')))}</pre>",
            f"<h2>Camera and workers</h2><p>{c['timeouts']} camera timeouts; worker restarts {e(_fmt(c['worker_restarts']))}" + (f"; <span class=bad>gave up: {e(', '.join(map(str, c['workers_gave_up'])))}</span>" if c["workers_gave_up"] else "") + "</p>",
            "<h2>Problems (WARN and worse)</h2>" + (f"<pre>{e(chr(10).join(rep['problems']))}</pre>" if rep["problems"] else "<p class=mut>none</p>")]
    if rep["profile"]:
        out.append(f"<h2>Profile</h2><pre>{e(rep['profile'])}</pre>")
    out.append("</body></html>")
    return "\n".join(out)
