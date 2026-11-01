"""Suggestions for the settings only the user changes (the `ask` knobs), said out loud (user, 2026-10-31).

A goal session ends by handing the robot back to the voice service. When the voice service starts, G2 tells the user each new suggestion and listens for the answer, no wake word
needed:

  "confirm"            the change is made in the user's own settings (for the ball punt: punt_settings.json)
  "cancel"             dropped; the judge will not suggest the same value again for a while (judge.RETRY_AFTER attempts)
  "review" / nothing   kept for later (the default when there is no answer): it stays in the report and in `g2goal suggestions`, and is not said again

Later: `g2goal confirm GOAL KNOB` / `g2goal cancel GOAL KNOB`. Every answer goes into the goal journal. `G2_GOAL_SUGGEST=0` turns the spoken offer off.
"""
from __future__ import annotations

import os
import re

from .journal import Journal, State

LATER_WORDS = {"review", "later", "wait", "maybe"}
CANCEL_WORDS = {"cancel", "cancelled", "no", "nope", "dont", "don't", "never", "nevermind", "drop", "skip"}
CONFIRM_WORDS = {"confirm", "confirmed", "yes", "yeah", "yep", "sure", "ok", "okay", "apply", "do"}


def parse_answer(text: str | None) -> str:
    """"confirm" | "cancel" | "later". Unclear words or silence are "later" (the user's default, 2026-10-31). A "review" or "later" anywhere wins, then a "no" or "cancel"
    ("okay cancel it" cancels), then a "yes" or "confirm"."""
    words = set(re.sub(r"[^a-z' ]", " ", (text or "").lower()).split())
    if not words or words & LATER_WORDS or "not now" in (text or "").lower():
        return "later"
    if words & CANCEL_WORDS:
        return "cancel"
    if words & CONFIRM_WORDS:
        return "confirm"
    return "later"


def pending(state: State, statuses=("new",)) -> list[tuple[str, str, str, dict]]:
    """[(goal id, conditions key, knob, entry)] with these statuses."""
    out = []
    for gid, per in state.data.items():
        for cond, st in per.items():
            for knob, e in (st.get("suggestions") or {}).items():
                if e.get("status", "new") in statuses:
                    out.append((gid, cond, knob, e))
    return out


def _knob(goal_id: str, knob: str):
    from .approach import make
    from .spec import load
    goal = load()[0].get(goal_id)
    if goal is None:
        return None, None, None
    ap = make(goal.approach)
    k = next((k for k in goal.knobs(ap.knobs()) if k.name == knob), None)
    return goal, ap, k


def describe(goal_id: str, knob: str, entry: dict) -> str:
    goal, _ap, k = _knob(goal_id, knob)
    title = goal.title.lower() if goal else goal_id
    if k is None:
        what = f"{knob} {entry.get('new')}"
        was = f" instead of {entry['old']}" if entry.get("old") is not None else ""
    else:
        what = f"{k.says()} {k.show(entry.get('new'))}"
        was = f" instead of {k.show(entry['old'])}" if entry.get("old") is not None else ""
    because = entry.get("because") or ""
    return (f"I have a suggestion from my practice at {title}: {what}{was}" + (f", because {because[:1].lower() + because[1:]}" if because else "")
            + ". Say confirm, cancel, or review.")


def resolve(goal_id: str, cond: str, knob: str, answer: str, *, state: State | None = None, journal: Journal | None = None) -> str:
    """Apply an answer. Returns what happened, in a short sentence G2 can say."""
    state = state or State()
    st = state.data.get(goal_id, {}).get(cond, {})
    e = (st.get("suggestions") or {}).get(knob)
    if e is None:
        return "That suggestion is gone."
    if answer == "confirm":
        goal, ap, k = _knob(goal_id, knob)
        try:
            if ap is None or not callable(getattr(ap, "set_user_setting", None)):
                raise ValueError("this goal's settings cannot be changed from here")
            ap.set_user_setting(knob, e["new"])
        except (ValueError, OSError) as err:
            e["status"] = "later"
            state.save()
            (journal or Journal()).write("suggestion", goal=goal_id, conditions=cond, knob=knob, new=e.get("new"), answer="failed", why=str(err))
            return f"I could not change it ({err}), so it waits in the report."
        st["suggestions"].pop(knob, None)
        said = f"Done: {k.says()} {k.show(e['new'])}." if k else "Done."
    elif answer == "cancel":
        st["suggestions"].pop(knob, None)
        st.setdefault("rejected", {})[f"{knob}={e.get('new')}"] = st.get("count", 0)
        said = "Okay, cancelled."
    else:
        e["status"] = "later"
        said = "Okay, it's in the report for later."
    state.save()
    (journal or Journal()).write("suggestion", goal=goal_id, conditions=cond, knob=knob, old=e.get("old"), new=e.get("new"), answer=answer)
    return said


def offer(speak, listen, *, timeout_s: float = 12.0, state: State | None = None, journal: Journal | None = None) -> int:
    """Say each new suggestion and act on the answer. `listen(timeout_s)` returns the words heard ("" for silence). Returns how many were offered. Never raises."""
    if os.environ.get("G2_GOAL_SUGGEST", "1") == "0":
        return 0
    try:
        state = state or State()
        items = pending(state)
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    for gid, cond, knob, e in items:
        try:
            speak(describe(gid, knob, e))
            try:
                heard = listen(timeout_s)
            except Exception:  # noqa: BLE001
                heard = ""
            speak(resolve(gid, cond, knob, parse_answer(heard), state=state, journal=journal))
            n += 1
        except Exception:  # noqa: BLE001
            continue
    return n
