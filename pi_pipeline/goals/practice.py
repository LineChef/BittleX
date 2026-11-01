"""'G2, practise' (user, 2026-10-31): G2 picks which goal to practise and says why; "G2, practise walls" names one.

Each goal gets   your priority  x  how much he needs it  x  whether it can be done now:

  priority   the goals.json order (highest first): 1.0, 0.8, 0.6 ... (never below 0.4)
  need       1 - his success rate over the last RECENT_N counted attempts under the current conditions (1.0 with none yet),
             + 0.25 when he has fewer than 10 attempts here (a new floor or new hardware), + up to 0.25 for the days since he last practised it (a week = all of it),
             - 0.3 x the share of its free settings that have settled
  now        the attachment it needs is fitted (else it is skipped); for the punt, the ball in the camera's picture right now (not seen: x 0.6, he will have to search)

The best one wins. A task starts its goal session; a standing goal (walls) is practised with an exploration roam of its `minutes`. Local only: no API call.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

RECENT_N = 10


@dataclass
class Choice:
    goal: object
    score: float
    sentence: str                 # what he says
    why: dict


def _recent(goal_id: str, cond_key: str, journal) -> list[bool]:
    from .journal import conditions_key
    rows = journal.read()
    cond_of = {r["session"]: conditions_key(r.get("conditions") or {}) for r in rows if r.get("kind") == "session_start" and r.get("goal") == goal_id}
    wrong = {(r.get("session"), r.get("index")) for r in rows if r.get("kind") == "verdict" and r.get("verdict") == "wrong"}
    out = [r["outcome"].get("success", False) for r in rows
           if r.get("kind") == "attempt" and r.get("goal") == goal_id and r["outcome"].get("score") is not None
           and cond_of.get(r.get("session")) == cond_key and (r.get("session"), r.get("index")) not in wrong]
    return out[-RECENT_N:]


def _last_time(goal_id: str, journal) -> float | None:
    t = None
    for r in journal.read():
        if r.get("kind") == "session_start" and r.get("goal") == goal_id:
            try:
                t = time.mktime(time.strptime(r["time"], "%Y-%m-%d %H:%M:%S"))
            except (KeyError, ValueError):
                pass
    return t


def score_goals(*, goals=None, order=None, attachment: str | None = None, ball_visible: bool | None = None, journal=None, state=None, now=None) -> list[Choice]:
    """Every goal that can be practised now, best first."""
    from .approach import make
    from .journal import Journal, State, conditions_key, current_conditions
    from .judge import Judge
    from .spec import load, priority
    goals = goals if goals is not None else load()[0]
    order = order or priority()
    journal = journal or Journal()
    state = state or State()
    now = now or time.time()
    if attachment is None:
        try:
            from ..attachments import current
            attachment = current()
        except Exception:  # noqa: BLE001
            attachment = "unknown"
    out = []
    for rank, gid in enumerate(order):
        g = goals.get(gid)
        if g is None:
            continue
        if g.needs_attachment and g.needs_attachment != attachment:
            continue
        try:
            ap = make(g.approach)
        except KeyError:
            continue
        cond_key = conditions_key(current_conditions(ap.conditions()))
        recent = _recent(gid, cond_key, journal)
        st = (state.data.get(gid) or {}).get(cond_key) or {}
        need = (1.0 - sum(recent) / len(recent)) if recent else 1.0
        why = {"recent": f"{sum(recent)} of {len(recent)}" if recent else None}
        if st.get("count", 0) < 10:
            need += 0.25
            why["new_here"] = True
        last = _last_time(gid, journal)
        days = (now - last) / 86400.0 if last else 7.0
        need += 0.25 * min(1.0, days / 7.0)
        free = [k for k in g.knobs(ap.knobs()) if k.control == "free"]
        if free and st:
            j = Judge(free, ap.diagnosis, dict(st))
            settled = sum(1 for k in free if j.is_settled(k.name))
            need -= 0.3 * settled / len(free)
        weight = max(0.4, 1.0 - 0.2 * rank)
        feasible = 1.0
        if gid == "ball_punt" and ball_visible is not None:
            why["ball_visible"] = ball_visible
            if not ball_visible:
                feasible = 0.6
        score = round(weight * max(0.05, need) * feasible, 3)
        out.append(Choice(g, score, _sentence(g, why), why))
    return sorted(out, key=lambda c: -c.score)


def _sentence(g, why: dict) -> str:
    parts = []
    if why.get("recent"):
        parts.append(f"{why['recent']} good here lately")
    elif why.get("new_here"):
        parts.append("I haven't practised it here yet")
    if why.get("ball_visible") is True:
        parts.append("and I can see the ball" if parts else "I can see the ball")
    elif why.get("ball_visible") is False:
        parts.append("though I'll have to find the ball first" if parts else "I'll have to find the ball first")
    name = getattr(g, "practice_say", "") or (g.title[:1].lower() + g.title[1:])
    return f"I'll practise {name}" + (f": {', '.join(parts)}." if parts else ".")


def named_goal(text_normalized: str, goals=None):
    """The goal named after "practise" ("practise walls"), or None."""
    from .spec import load
    goals = goals if goals is not None else load()[0]
    words = text_normalized.split()
    for verb in ("practise", "practice"):
        if verb in words:
            rest = " ".join(words[words.index(verb) + 1:])
            if not rest:
                return None
            for g in goals.values():
                for w in g.practice_words + (g.id, g.title.lower()):
                    if rest == w or rest.startswith(w + " ") or rest.endswith(" " + w):
                        return g
    return None


def choose(text_normalized: str = "", **kw) -> tuple[object | None, str]:
    """(the goal to practise, what he says). A named goal wins if it can be done now."""
    choices = score_goals(**kw)
    named = named_goal(text_normalized)
    if named is not None:
        hit = next((c for c in choices if c.goal.id == named.id), None)
        if hit is None:
            return None, f"I can't practise {named.title.lower()} right now" + (f": it needs the {named.needs_attachment}." if named.needs_attachment else ".")
        return hit.goal, hit.sentence
    if not choices:
        return None, "I have nothing I can practise right now."
    return choices[0].goal, choices[0].sentence
