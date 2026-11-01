"""Standing goals in practice (goals plan, "Choosing between goals"): they have no sessions of their own, so the activities call in here.

  apply(goal_id)                         at the start of an activity (an exploration, a ball chase): put his current values for the goal's settings into the code
  learn(goal_id, events, source)         at the end of one (or after each chase attempt): score each encounter, judge it, record it, save

Both never raise: a standing goal must never disturb the activity it rides on. Each `learn` is written to the goal journal as a session with the activity as its mode.
"""
from __future__ import annotations

import logging
import time
import uuid

log = logging.getLogger("g2.goals.standing")


def _parts(goal_id: str, conditions: dict | None = None, state=None):
    from .approach import make
    from .journal import State, conditions_key, current_conditions
    from .judge import Judge
    from .overrides import for_conditions
    from .spec import load
    goal = load()[0].get(goal_id)
    if goal is None:
        return None
    ap = make(goal.approach)
    cond = conditions if conditions is not None else current_conditions(ap.conditions())
    key = conditions_key(cond)
    state = state or State()
    judge = Judge(goal.knobs(ap.knobs()), ap.diagnosis, state.for_goal(goal.id, key), stage_of=getattr(ap, "stage_of", None), overrides=for_conditions(goal.id, key))
    return goal, ap, cond, key, state, judge


def apply(goal_id: str = "walls", *, conditions: dict | None = None, state=None) -> dict | None:
    """Put his current values for a standing goal into the code. Returns them (None when it could not)."""
    try:
        parts = _parts(goal_id, conditions, state)
        if parts is None:
            return None
        goal, ap, cond, _key, state, judge = parts
        base = ap.base_settings()
        if judge.state.get("count"):
            values = judge.settings(base)
        else:                                                             # new conditions (a floor, hardware, a wall calibration): start from his best elsewhere
            from .prior import find_prior
            prior, prior_from = find_prior(goal, ap, list(judge.knobs.values()), state, cond, base, judge.ov)
            values = judge.begin_session(base, prior=prior, prior_from=prior_from)
            if prior_from:
                judge.state["started_from"] = prior_from
        note = getattr(ap, "condition_note", None)
        if callable(note):
            judge.state.update(note())                                    # e.g. the wall calibration's points, for carrying settings to the next one
        state.save()
        if callable(getattr(ap, "apply", None)):
            ap.apply(values)
        return values
    except Exception:  # noqa: BLE001
        log.exception("could not apply the %s goal's settings", goal_id)
        return None


def learn(goal_id: str, events: list, source: str, *, used: dict | None = None, conditions: dict | None = None, state=None, journal=None) -> int:
    """Score `events` (goals/walls.py events) as encounters and judge each one. Returns how many were counted."""
    try:
        from .journal import Journal
        from .walls import score_encounters
        if not events:
            return 0
        parts = _parts(goal_id, conditions, state)
        if parts is None:
            return 0
        goal, ap, cond, _key, state, judge = parts
        outcomes = score_encounters(events) if goal.approach == "walls" else []
        if not outcomes:
            return 0
        journal = journal or Journal()
        note = getattr(ap, "condition_note", None)
        if callable(note) and "wallcal_points" not in judge.state:
            judge.state.update(note())
        settings = used or judge.settings(ap.base_settings())
        session = "s" + uuid.uuid4().hex[:7]
        journal.write("session_start", session=session, goal=goal.id, title=goal.title, mode=source, conditions=cond, settings=settings, controls={k: v.control for k, v in judge.knobs.items()},
                      learned_from=judge.state.get("count", 0))
        ok = 0
        for i, o in enumerate(outcomes, 1):
            from .journal import next_number
            n = next_number(judge.state)
            judge.state["last_number"] = n
            journal.write("attempt", session=session, goal=goal.id, index=i, number=n, ended=o.code, seconds=0.0, settings=settings,
                          outcome={"code": o.code, "score": o.score, "success": o.success, "text": o.text, "stages": o.stages}, numbers=o.numbers, extra={}, trace=[])
            for d in judge.update(n, o, settings):
                journal.write("decision", session=session, goal=goal.id, index=i, **d.as_dict())
            ok += int(o.success)
        # no finish() here: a standing goal keeps exploring from one activity to the next (finish puts every setting back on its best value)
        judge.state["updated"] = time.time()
        state.save()
        journal.write("session_end", session=session, goal=goal.id, why=source, attempts=len(outcomes), successes=ok, minutes=0.0, lessons=[], lessons_saved=0,
                      settings_now=judge.settings(ap.base_settings()), mode=source)
        if callable(getattr(ap, "apply", None)):
            ap.apply(judge.settings(ap.base_settings()))                    # the next activity starts with what he just learned
        return len(outcomes)
    except Exception:  # noqa: BLE001
        log.exception("could not learn the %s goal from %s", goal_id, source)
        return 0
