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
import sys
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_DIR = "~/Desktop/G2Memory/goals"
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):                 # g2_goal_edits (tools/) and pi_pipeline (repo root) import from anywhere
    if _p not in sys.path:
        sys.path.insert(0, _p)
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


SYNC_STALE_H = {"goals": 24, "pictures": 48, "walklogs": 72, "walls": 72, "memorydb": 48, "logs": 72}     # the same limits as tools/g2_sync.sh


def sync_status(path: str, now: float | None = None) -> list[dict]:
    """[{task, last_ok (12-hour), age_h, stale, failed}] from ~/Desktop/G2Memory/sync_status.json (tools/g2_sync.sh)."""
    d = _json(path) or {}
    now = time.time() if now is None else now
    out = []
    for task, stale_h in SYNC_STALE_H.items():
        t = d.get(task) or {}
        ok = t.get("last_ok")
        age = (now - time.mktime(time.strptime(ok, "%Y-%m-%d %H:%M:%S"))) / 3600 if ok else None
        out.append({"task": task, "last_ok": nice_time(ok) if ok else "never", "age_h": None if age is None else round(age, 1),
                    "stale": age is None or age > stale_h, "failed": t.get("result") == "failed"})
    return out


def _definitions(d: str) -> tuple[dict, list[str]]:
    """({goal id: {definition fields, knobs: [setting catalog]}}, priority order) from the goals file on this Mac plus the built-in goals."""
    try:
        from pi_pipeline.goals import spec
        from pi_pipeline.goals.approach import make
        path = os.path.join(d, "goals.json")
        goals, _problems = spec.load(path)
        order = spec.priority(path)
    except Exception:  # noqa: BLE001  (the tab still shows the history without the definitions)
        return {}, []
    out = {}
    for gid, g in goals.items():
        try:
            knobs = [{"name": k.name, "label": k.says(), "kind": k.kind, "lo": k.lo, "hi": k.hi, "step": k.step, "options": list(k.options), "unit": k.unit, "control": k.control}
                     for k in g.knobs(make(g.approach).knobs())]
        except Exception:  # noqa: BLE001
            knobs = []
        out[gid] = {"id": gid, "title": g.title, "approach": g.approach, "kind": g.kind, "attempts": g.attempts, "minutes": g.minutes, "min_pack_pct": g.min_pack_pct,
                    "target_successes": g.target_successes or 0, "rest_between_s": g.rest_between_s, "start_words": list(g.start_words), "needs_attachment": g.needs_attachment,
                    "controls": dict(g.controls), "knobs": knobs}
    return out, order


def _override_rows(ov: dict) -> list[dict]:
    """The overrides file's {scope: {pins, limits, banned}} as flat rows for the tab."""
    rows = []
    for scope, e in (ov or {}).items():
        for knob, v in ((e or {}).get("pins") or {}).items():
            rows.append({"kind": "pin", "knob": knob, "value": v, "scope": scope})
        for knob, v in ((e or {}).get("limits") or {}).items():
            rows.append({"kind": "limit", "knob": knob, "lo": v[0] if v else None, "hi": v[1] if v else None, "scope": scope})
        for knob, vals in ((e or {}).get("banned") or {}).items():
            for vk in (vals or {}):
                rows.append({"kind": "banned", "knob": knob, "value": vk, "scope": scope})
    return rows


def _suggestions(state: dict) -> list[dict]:
    out = []
    for gid, per in (state or {}).items():
        for cond, st in (per or {}).items():
            for knob, e in ((st or {}).get("suggestions") or {}).items():
                if e.get("status", "new") in ("new", "later"):
                    try:
                        from pi_pipeline.goals.suggestions import describe
                        text = describe(gid, knob, e)
                    except Exception:  # noqa: BLE001
                        text = f"{knob}: {json.dumps(e)[:200]}"
                    out.append({"goal": gid, "knob": knob, "conditions": cond, "status": e.get("status", "new"), "text": text})
    return out


def _age_hours(stamp: str) -> float | None:
    """Hours since a pulled_at.txt time ('2026-11-04 8:34 AM EST'); None when it cannot be read."""
    m = re.match(r"(\d{4}-\d\d-\d\d) (\d{1,2}):(\d\d) (AM|PM)", (stamp or "").strip())
    if not m:
        return None
    try:
        t = time.mktime(time.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)} {m.group(4)}", "%Y-%m-%d %I:%M %p"))
    except ValueError:
        return None
    return round((time.time() - t) / 3600, 1)


# ---- which lessons are worth keeping (user, 2026-11-06: judge them on the evidence, not on wording)
# A lesson is a note G2 saved after he KEPT a setting value ("Searching by turn works best so far: 2 of 2 good, against...") or UNDID one ("I won't try that again for a while"). The note's counts
# are a snapshot: a lesson written after 2 attempts says little. So each lesson is re-judged on what the journal holds NOW, for the same goal, settings value, floor and hardware, counting only attempts
# that still count (not retracted, current scoring version):
#   - the value's record n/h, with a 95% Wilson range, and how likely it still beats the best alternative tried (Beta posterior, 4000 draws, fixed seed);
#   - keep: 8+ attempts and it still beats the alternatives (75%+ likely, or none tried 3+ times); an undo lesson whose value really does fail (3+ tries, under 40% good)
#   - delete: nothing behind it still counts; an older lesson on the same setting and value than a newer one; 5+ attempts and the alternatives now beat it (under 25%) or it succeeds under a third;
#     an undo lesson older than 30 days ("for a while" is over); a lesson that names a date or time
#   - unsure: everything else, shown with its numbers so more attempts can settle it
MIN_KEEP_N, MIN_JUDGE_N, ALT_MIN_N = 8, 5, 3
UNDO_DAYS = 30


def wilson(h: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = h / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def p_better(h1: int, n1: int, h2: int, n2: int, draws: int = 4000, seed: int = 7) -> float:
    """How likely the first value's true success rate is above the second's, from Beta(1+h, 1+n-h) posteriors."""
    import random
    rng = random.Random(seed)
    return sum(rng.betavariate(1 + h1, 1 + n1 - h1) > rng.betavariate(1 + h2, 1 + n2 - h2) for _ in range(draws)) / draws


def lesson_review(journal: list[dict], lessons: list[dict], titles: dict, cond_of: dict, now: float | None = None) -> list[dict]:
    """[{id, goal, text, verdict: keep|delete|unsure, why, n, h}] for every saved goal lesson. See the block comment above for the rules."""
    from pi_pipeline.goals.curate import attempt_epoch, epoch_now
    from pi_pipeline.memory.store import has_temporal_detail
    now = now or time.time()
    gone = {k for k, v in _verdicts(journal).items() if v.get("verdict") == "wrong"}
    attempts = [r for r in journal if r.get("kind") == "attempt" and r.get("number") is not None and (r.get("outcome") or {}).get("score") is not None
                and (r.get("session"), r.get("index")) not in gone and attempt_epoch(r) >= epoch_now(r.get("goal"))]
    decisions = [r for r in journal if r.get("kind") == "decision" and r.get("note") and r.get("knob") and r.get("action") in ("kept", "undo")]
    out, by_key = [], {}
    for les in sorted(lessons, key=lambda x: int(x.get("id") or 0)):
        text = les.get("lesson", "")
        backing = next((d for d in decisions if d["note"] in text), None)
        goal = next((g for g, t in titles.items() if text.startswith(t + ":")), None)
        row = {"id": les.get("id"), "goal": titles.get(goal, goal or "?"), "text": text.split(":", 1)[-1].strip() if goal else text, "verdict": "unsure", "why": "", "n": 0, "h": 0}
        out.append(row)
        if has_temporal_detail(row["text"]):
            row.update(verdict="delete", why="names a date or time: a lesson should stay true")
            continue
        if backing is None:
            row["why"] = "no record in the journal says where it came from, so it is left alone"
            continue
        knob, val, cond = backing["knob"], backing["new"], cond_of.get(backing.get("session"), {})
        by_key.setdefault((backing["goal"], knob, json.dumps(val), json.dumps(cond, sort_keys=True)), []).append(row)
        pool = [a for a in attempts if a.get("goal") == backing["goal"] and cond_of.get(a.get("session"), {}) == cond]
        rec = {}
        for a in pool:
            v = (a.get("settings") or {}).get(knob)
            h, n = rec.get(json.dumps(v), (0, 0))
            rec[json.dumps(v)] = (h + (1 if (a.get("outcome") or {}).get("success") else 0), n + 1)
        h, n = rec.get(json.dumps(val), (0, 0))
        row["n"], row["h"] = n, h
        age_days = (now - time.mktime(time.strptime(backing["time"], "%Y-%m-%d %H:%M:%S"))) / 86400.0
        alts = {k: v for k, v in rec.items() if k != json.dumps(val) and v[1] >= ALT_MIN_N}
        best_alt = max(alts.items(), key=lambda kv: kv[1][0] / kv[1][1]) if alts else None
        lo, hi = wilson(h, n)
        rng = f"{h} of {n} good (between {round(lo * 100)}% and {round(hi * 100)}% likely)"
        if n == 0:
            row.update(verdict="delete", why="none of the attempts behind it still count (retracted, or from an older scoring version)")
        elif backing["action"] == "undo":
            worse = p_better(best_alt[1][0], best_alt[1][1], h, n) if best_alt else None        # how likely the best alternative really does better than the value he undid
            if n >= ALT_MIN_N and ((worse is not None and worse >= 0.75) or (best_alt is None and h / n < 0.4)):
                row.update(verdict="keep", why=f"confirmed: {rng} with it" + ("" if worse is None else f"; the best alternative ({best_alt[1][0]} of {best_alt[1][1]}) does better in {round(worse * 100)}% of simulations"))
            elif age_days > UNDO_DAYS:
                row.update(verdict="delete", why=f"\u201cfor a while\u201d is over ({round(age_days)} days) and the data does not confirm it ({rng})")
            else:
                row.update(why=f"not confirmed yet: {rng}")
        else:
            p = p_better(h, n, best_alt[1][0], best_alt[1][1]) if best_alt else None
            vs = "" if p is None else f"; beats the best alternative ({best_alt[1][0]} of {best_alt[1][1]}) in {round(p * 100)}% of simulations"
            if n >= MIN_KEEP_N and ((p is not None and p >= 0.75) or (p is None and h / n >= 1 / 3)):
                row.update(verdict="keep", why=f"supported: {rng}{vs}")
            elif n >= MIN_JUDGE_N and p is not None and p < 0.25:
                row.update(verdict="delete", why=f"now looks worse than an alternative: {rng}{vs}")
            elif n >= MIN_JUDGE_N and p is None and h / n < 1 / 3:                        # no alternative to compare with: judged on its own record
                row.update(verdict="delete", why=f"it mostly fails now and nothing else was tried to compare: {rng}")
            else:
                row.update(why=f"not enough evidence yet: {rng}{vs}" if n < MIN_KEEP_N else f"unclear: {rng}{vs}")
    for rows in by_key.values():                                     # the same setting and value learned again: only the newest note stays
        for old in rows[:-1]:
            if old["verdict"] != "delete":
                old.update(verdict="delete", why=f"said again, newer, in lesson #{rows[-1]['id']}")
    return out


def build(folder: str | None = None) -> dict:
    d = os.path.expanduser(folder or os.environ.get("G2_GOALS_DIR", DEFAULT_DIR))
    journal = _lines(os.path.join(d, "goal_journal.jsonl"))
    lessons = _lines(os.path.join(d, "lessons.jsonl"))
    state = _json(os.path.join(d, "goal_state.json")) or {}
    overrides = _json(os.path.join(d, "goal_overrides.json")) or {}
    report = _text(os.path.join(d, "goal_curation", "curation_report.md"))
    flags = _flags(report)
    verdicts = _verdicts(journal)
    titles, goals, cond_of = {}, {}, {}
    for r in journal:
        if r.get("kind") == "session_start":
            titles[r["goal"]] = r.get("title") or r["goal"]
            c = r.get("conditions") or {}
            cond_of[r.get("session")] = {k: v for k, v in c.items() if k in ("attachment", "floor", "hw")}
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
                                  "conditions": cond_of.get(r.get("session"), {}), "retracted": retracted, "retired": bool(retracted and (v or {}).get("note", "").startswith("retired")), "notes": (v or {}).get("note", ""),
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
    defs, order = _definitions(d)
    from g2_goal_edits import history, pending, with_text
    for gid, g in goals.items():
        df = defs.get(gid) or {}
        g["definition"] = df
        g["kind"] = df.get("kind", "task")
        g["override_rows"] = _override_rows(overrides.get(gid) or {})
        g["conditions_seen"] = sorted({json.dumps(a["conditions"], sort_keys=True) for a in g["attempts"]})
        for a in g["attempts"]:
            a["session_why"] = next((s["why"] for s in g["sessions"] if s["session"] == a["session"]), None)
    for gid, df in defs.items():                                     # a goal with no attempts yet is still listed (so it can be edited)
        if gid not in goals:
            goals[gid] = {"id": gid, "title": df["title"], "lessons": [], "sessions": [], "attempts": [], "learned": [], "overrides": {}, "counted": 0, "successes": 0,
                          "definition": df, "kind": df["kind"], "override_rows": _override_rows(overrides.get(gid) or {}), "conditions_seen": [], "settings_now": {}, "trend": []}
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
    try:
        review = lesson_review(journal, lessons, {gid: g["title"] for gid, g in goals.items()}, cond_of)
    except Exception:  # noqa: BLE001 -- a hint must never break the tab
        review = []
    pulled = _text(os.path.join(d, "pulled_at.txt")).strip()
    return {"lesson_review": review, "pulled": pulled, "pulled_age_h": _age_hours(pulled), "priority": order, "suggestions": _suggestions(state), "pending": with_text(pending(d)), "edit_history": history(d),
            "goals": list(goals.values()), "other_lessons": unmatched, "memory": _memory(os.path.join(d, "memory_log.jsonl")),
            "turns": _turns(os.path.join(d, "turn_log.jsonl")), "curation": report.strip(), "folder": d,
            "sync": sync_status(os.path.join(os.path.dirname(d.rstrip("/")), "sync_status.json"))}
