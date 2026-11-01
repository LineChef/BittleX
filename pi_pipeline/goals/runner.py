"""One goal session (goals plan, "Session flow"): up to the goal's attempts, each judged before the next. Started by the user, everything after is automatic.

Before each attempt: the stop flag, the time budget and the pack % (with the voice service stopped there is no battery watch, so it is read here). After each: score, judge,
write the attempt and the decisions, set the next attempt's settings. A fall ends the session (with the arm, fall recovery is off). At the end: up to three lessons are saved as
memory facts and the learned state is saved.
"""
from __future__ import annotations

import time
import uuid
from typing import Callable

from .approach import Approach, AttemptContext
from .journal import Journal, State, conditions_key, current_conditions, lessons_from, save_lessons
from .judge import Judge
from .spec import Goal


class GoalSession:
    def __init__(self, goal: Goal, approach: Approach, *, journal: Journal | None = None, state: State | None = None, stop: Callable[[], bool] = lambda: False,
                 say: Callable[[str], None] = print, announce: Callable[[str], None] | None = None, conditions: dict | None = None, sleep=time.sleep,
                 clock=time.monotonic, save_memory: bool = True, memory_store=None, overrides: dict | None = None, rng=None):
        self.goal, self.approach = goal, approach
        self.journal = journal or Journal()
        self.state = state or State()
        self.stop, self.say, self.announce, self.sleep, self.clock = stop, say, announce, sleep, clock
        self.cond = conditions if conditions is not None else current_conditions(approach.conditions())
        self.cond_key = conditions_key(self.cond)
        self.save_memory, self.memory_store = save_memory, memory_store
        self.knobs = goal.knobs(approach.knobs())
        if overrides is None:
            from . import overrides as ovr
            overrides = ovr.for_conditions(goal.id, self.cond_key)
        self.overrides = overrides
        self.judge = Judge(self.knobs, approach.diagnosis, self.state.for_goal(goal.id, self.cond_key), stage_of=getattr(approach, "stage_of", None), overrides=overrides, rng=rng)
        self.session = uuid.uuid4().hex[:8]

    def _speak(self, text: str) -> None:
        if self.announce is not None:
            try:
                self.announce(text)
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> dict:
        g = self.goal
        base = self.approach.base_settings()
        start_settings = self.judge.begin_session(base)
        self.journal.write("session_start", session=self.session, goal=g.id, title=g.title, conditions=self.cond, budget={"attempts": g.attempts, "minutes": g.minutes,
                           "min_pack_pct": g.min_pack_pct, "target_successes": g.target_successes}, settings=start_settings,
                           controls={k.name: k.control for k in self.knobs}, learned_from=self.judge.state.get("count", 0), overrides=self.overrides)
        self.say(f"goal session {self.session}: {g.title}, up to {g.attempts} attempts ({self.cond_key}); {self.judge.state.get('count', 0)} attempts learned from before")
        t0 = self.clock()
        successes, counted, why = 0, 0, "attempts"
        decisions_all: list[dict] = []
        ctx = AttemptContext(stop=self.stop, say=self.say, announce=self.announce)
        n_prev = self.judge.state.get("count", 0)
        try:
            self.approach.open()
            for i in range(1, g.attempts + 1):
                if self.stop():
                    why = "stopped"
                    break
                if (self.clock() - t0) / 60.0 >= g.minutes:
                    why = "time"
                    break
                ok, bat = self.approach.battery_ok(g.min_pack_pct)
                if not ok:
                    why = "battery"
                    self.say(f"not starting attempt {i}: {bat}")
                    self._speak("My battery is low, so I'm stopping.")
                    break
                settings = self.judge.settings(base)
                n = n_prev + counted + 1                              # the attempt's number across sessions (this goal and these conditions)
                self.say(f"attempt {i} of {g.attempts} (#{n}), {bat}")
                result = self.approach.run_attempt(settings, ctx)
                outcome = self.approach.score(result, settings)
                self.journal.write("attempt", session=self.session, goal=g.id, index=i, number=n if outcome.counted else None, ended=result.ended, seconds=result.seconds,
                                   settings=settings, outcome={"code": outcome.code, "score": outcome.score, "success": outcome.success, "text": outcome.text, "stages": outcome.stages},
                                   numbers=outcome.numbers, extra=result.extra, trace=result.trace)
                decisions = self.judge.update(n, outcome, settings)
                for d in decisions:
                    row = self.journal.write("decision", session=self.session, goal=g.id, index=i, **d.as_dict())
                    decisions_all.append(row)
                    self.say("  " + d.note)
                self.state.save()                                     # after every attempt: a crash keeps what was learned
                if outcome.counted:
                    counted += 1
                    successes += int(outcome.success)
                if outcome.counted:
                    self._speak("Got it." if outcome.success else "Missed.")
                if outcome.fell:
                    why = "fell"
                    break
                if result.ended == "battery":
                    why = "battery"
                    break
                if result.ended == "stopped" or self.stop():
                    why = "stopped"
                    break
                if g.target_successes and successes >= g.target_successes:
                    why = "target"
                    break
                if i < g.attempts:
                    self.sleep(g.rest_between_s)
        finally:
            try:
                self.approach.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                for d in self.judge.finish(base, n_prev + counted):
                    decisions_all.append(self.journal.write("decision", session=self.session, goal=g.id, index=None, **d.as_dict()))
                    self.say("  " + d.note)
            except Exception:  # noqa: BLE001
                pass
            lessons = lessons_from(decisions_all, g.title)
            saved = save_lessons(lessons, self.memory_store) if self.save_memory else 0
            self.state.save()
            summary = {"session": self.session, "goal": g.id, "why": why, "attempts": counted, "successes": successes, "minutes": round((self.clock() - t0) / 60.0, 1),
                       "lessons": lessons, "lessons_saved": saved, "settings_now": self.judge.settings(base)}
            self.journal.write("session_end", **summary)
            self.say(f"session ended ({why}): {successes} of {counted} counted attempts succeeded; {saved} lesson(s) saved to memory")
        return summary
