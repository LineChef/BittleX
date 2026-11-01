"""Attempts made outside a goal session still teach G2 (user-approved 2026-10-31): a plain "G2, punt" (or `g2punt`) is scored like a goal attempt and added to the ball-punt
goal's records under the current conditions. Nothing is changed: the next plain punt uses the user's own settings as before, and only a goal session moves a setting.

Written to the goal journal as a one-attempt session with mode "plain punt", so the report shows it. Never raises: a punt must never fail because of this.
"""
from __future__ import annotations

import logging
import time
import uuid

log = logging.getLogger("g2.goals.observe")


def plain_punt(trace: list, ended: str, seconds: float, settings: dict, pack_pct=None, *, state=None, journal=None, conditions: dict | None = None, goal_id: str = "ball_punt") -> str | None:
    """Score one plain punt attempt and add it to the goal's records. Returns the outcome's text, or None when it was not counted or something failed."""
    try:
        from .approach import AttemptResult
        from .ball_punt import BallPunt
        from .journal import Journal, State, conditions_key, current_conditions
        from .judge import Judge
        from .overrides import for_conditions
        from .spec import load
        goal = load()[0].get(goal_id)
        if goal is None:
            return None
        ap = BallPunt()
        result = AttemptResult(ended, round(float(seconds), 1), list(trace))
        outcome = ap.score(result, settings)
        cond = conditions if conditions is not None else current_conditions(ap.conditions())
        key = conditions_key(cond)
        state = state or State()
        journal = journal or Journal()
        judge = Judge(goal.knobs(ap.knobs()), ap.diagnosis, state.for_goal(goal.id, key), stage_of=ap.stage_of, overrides=for_conditions(goal.id, key))
        n = judge.state.get("count", 0) + 1
        session = "p" + uuid.uuid4().hex[:7]
        journal.write("session_start", session=session, goal=goal.id, title=goal.title, mode="plain punt", conditions=cond, settings=settings, controls={}, learned_from=n - 1)
        journal.write("attempt", session=session, goal=goal.id, index=1, number=n if outcome.counted else None, ended=ended, seconds=result.seconds, settings=settings,
                      outcome={"code": outcome.code, "score": outcome.score, "success": outcome.success, "text": outcome.text, "stages": outcome.stages},
                      numbers=outcome.numbers, extra={}, trace=result.trace, pack_pct=pack_pct)
        for d in judge.observe(n, outcome, settings):
            journal.write("decision", session=session, goal=goal.id, index=1, **d.as_dict())
        judge.state["updated"] = time.time()
        state.save()
        journal.write("session_end", session=session, goal=goal.id, why=ended, attempts=int(outcome.counted), successes=int(outcome.success), minutes=round(result.seconds / 60, 1),
                      lessons=[], lessons_saved=0, settings_now=settings, mode="plain punt")
        return outcome.text if outcome.counted else None
    except Exception:  # noqa: BLE001
        log.exception("could not add the plain punt to the goal's records")
        return None
