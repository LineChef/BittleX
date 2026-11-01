"""What the Goals tab of the review page shows (user, 2026-11-01): for each goal G2 works on, what he learned, how it is going, and what he is using now.

Everything comes from the copy of the goal data on this Mac (`g2goal pull` / the deploy keep ~/Desktop/G2Memory/goals current), so the tab works with G2 and the Pi off. It only reads.

  build(folder)   ->  {"pulled": text, "goals": [...], "memory": {...}, "curation": text}

Each goal: its lessons (the notes he saved to memory, with the date and a flag when the curation doubts one), its sessions, every attempt (retracted ones marked), the values he
has tried per setting with how often each worked (best first), the settings he uses now, the focus setting, the turns he made (from turn_log.jsonl, with the cause) and the overrides you set.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_DIR = "~/Desktop/G2Memory/goals"
EASTERN = ZoneInfo("America/New_York")


def _lines(path: str) -> list[dict]:
    out = []
    try:
        with open(path) as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        out.append(json.loads(ln))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def _json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _text(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def nice_time(stamp: str | None) -> str:
    """'Nov 1, 4:35 PM' (Eastern, 12-hour) from a journal time ('2026-11-01 16:35:38', already local) or an ISO time with an offset."""
    if not stamp:
        return ""
    try:
        if "T" in stamp and ("+" in stamp[10:] or stamp.endswith("Z")):
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(EASTERN)
        else:
            dt = datetime.strptime(stamp[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%b %-d, %-I:%M %p")
    except ValueError:
        return stamp


def _verdicts(rows: list[dict]) -> dict:
    out = {}
    for r in rows:
        if r.get("kind") == "verdict":
            out[(r.get("session"), r.get("index"))] = r
    return out


def _flags(report: str) -> dict:
    """{lesson id: why flagged} from the curation report's lines."""
    out = {}
    for m in re.finditer(r"lesson #(\d+) flagged: ([^:]+(?:\([^)]*\))?[^:]*):", report):
        out[int(m.group(1))] = m.group(2).strip()
    return out


def _best_values(state_for_goal: dict | None) -> list[dict]:
    """Per setting the values tried, most-evidence first: [{setting, now, tried: [{value, tries, good}]}], the focus setting first."""
    if not state_for_goal:
        return []
    cond = next(iter(state_for_goal.values()), None) if isinstance(state_for_goal, dict) else None
    if not isinstance(cond, dict):
        return []
    focus = cond.get("focus")
    now = cond.get("current") or {}
    out = []
    for knob, vals in (cond.get("values") or {}).items():
        tried = [{"value": v.get("v"), "tries": v.get("n", 0), "good": v.get("hits", 0)} for v in vals.values() if v.get("n", 0) > 0]
        if not tried:
            continue
        tried.sort(key=lambda t: (-t["tries"], str(t["value"])))
        out.append({"setting": knob, "now": now.get(knob), "focus": knob == focus, "tried": tried})
    out.sort(key=lambda r: (not r["focus"], r["setting"]))
    return out


def _turns(path: str, days: float = 3.0) -> dict:
    rows = _lines(path)
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days * 86400))
    rows = [r for r in rows if r.get("time", "") >= cutoff]
    by = Counter((r.get("kind"), r.get("direction")) for r in rows)
    causes = Counter(r.get("cause") for r in rows)
    recent = [{"time": nice_time(r.get("time")), "kind": r.get("kind"), "direction": r.get("direction"), "degrees": r.get("degrees"), "cause": r.get("cause"), "why": r.get("why"),
               "ball": (r.get("ball") or {}).get("distance_in"), "ball_deg": (r.get("ball") or {}).get("bearing_deg"), "wall_in": r.get("wall_in")} for r in rows[-25:]]
    return {"days": days, "count": len(rows), "by_kind": [{"kind": k[0], "direction": k[1], "n": n} for k, n in sorted(by.items(), key=lambda x: -x[1])],
            "causes": [{"cause": c, "n": n} for c, n in causes.most_common()], "recent": list(reversed(recent))}


def _memory(path: str) -> dict:
    rows = [r for r in _lines(path) if r.get("kind") == "sample" and r.get("avail_mb") is not None]
    if not rows:
        return {}
    lo = min(rows, key=lambda r: r["avail_mb"])
    return {"lowest_mb": lo["avail_mb"], "when": nice_time(lo.get("t")), "samples": len(rows), "swap_mb": max(r.get("swap_used_mb", 0) or 0 for r in rows),
            "oom_kills": (rows[-1].get("oom_kills", 0) or 0) - (rows[0].get("oom_kills", 0) or 0)}


def build(folder: str | None = None) -> dict:
    d = os.path.expanduser(folder or os.environ.get("G2_GOALS_DIR", DEFAULT_DIR))
    journal = _lines(os.path.join(d, "goal_journal.jsonl"))
    lessons = _lines(os.path.join(d, "lessons.jsonl"))
    state = _json(os.path.join(d, "goal_state.json")) or {}
    overrides = _json(os.path.join(d, "goal_overrides.json")) or {}
    report = _text(os.path.join(d, "goal_curation", "curation_report.md"))
    flags = _flags(report)
    verdicts = _verdicts(journal)
    titles, goals = {}, {}
    for r in journal:
        if r.get("kind") == "session_start":
            titles[r["goal"]] = r.get("title") or r["goal"]
    for gid in list(dict.fromkeys([*state.keys(), *[r.get("goal") for r in journal if r.get("goal")]])):
        goals[gid] = {"id": gid, "title": titles.get(gid, gid), "lessons": [], "sessions": [], "attempts": [], "learned": _best_values(state.get(gid)),
                      "overrides": overrides.get(gid) or {}, "counted": 0, "successes": 0}
    for r in journal:
        g = goals.get(r.get("goal"))
        if g is None:
            continue
        if r["kind"] == "attempt":
            v = verdicts.get((r.get("session"), r.get("index")))
            o = r.get("outcome") or {}
            retracted = v is not None and v.get("verdict") == "wrong"
            counted = r.get("number") is not None and o.get("score") is not None and not retracted
            g["attempts"].append({"number": r.get("number"), "time": nice_time(r.get("time")), "raw_time": r.get("time"), "session": r.get("session"), "ended": r.get("ended"),
                                  "seconds": r.get("seconds"), "outcome": o.get("code"), "text": o.get("text"), "success": bool(o.get("success")), "counted": counted,
                                  "retracted": retracted, "retired": bool(retracted and (v or {}).get("note", "").startswith("retired")), "notes": (v or {}).get("note", ""),
                                  "settings": r.get("settings") or {}})
            if counted:
                g["counted"] += 1
                g["successes"] += 1 if o.get("success") else 0
        elif r["kind"] == "session_end":
            g["sessions"].append({"time": nice_time(r.get("time")), "raw_time": r.get("time"), "session": r.get("session"), "why": r.get("why"), "attempts": r.get("attempts"),
                                  "successes": r.get("successes"), "minutes": r.get("minutes"), "settings_now": r.get("settings_now") or {}})
    for g in goals.values():
        g["attempts"].sort(key=lambda a: a["raw_time"] or "", reverse=True)
        g["sessions"].sort(key=lambda s: s["raw_time"] or "", reverse=True)
        g["settings_now"] = (g["sessions"][0]["settings_now"] if g["sessions"] else {})
        g["trend"] = [{"session": s["time"], "rate": (s["successes"] / s["attempts"]) if s.get("attempts") else None, "attempts": s.get("attempts"), "successes": s.get("successes")}
                      for s in reversed(g["sessions"]) if s.get("attempts")][-8:]
    unmatched = []
    for les in lessons:
        text = les.get("lesson", "")
        row = {"id": les.get("id"), "time": nice_time(les.get("time")), "text": text, "flag": flags.get(les.get("id"))}
        for g in goals.values():
            if text.startswith(g["title"] + ":"):
                row["text"] = text[len(g["title"]) + 1:].strip()
                g["lessons"].append(row)
                break
        else:
            unmatched.append(row)
    return {"pulled": _text(os.path.join(d, "pulled_at.txt")).strip(), "goals": list(goals.values()), "other_lessons": unmatched, "memory": _memory(os.path.join(d, "memory_log.jsonl")),
            "turns": _turns(os.path.join(d, "turn_log.jsonl")), "curation": report.strip(), "folder": d}
