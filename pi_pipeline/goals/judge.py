"""How G2 judges an attempt, on the Pi with no API call (goals plan, "How G2 judges an attempt"). Shared by every goal.

After each counted attempt:

1. A change being tried (a "trial") gets the attempt's score. After TRIAL_N attempts with it, its mean is compared with the attempts just before it (the baseline): kept if it is
   better, undone if not (one more attempt first when it is too close to call, up to TRIAL_MAX). A fall during a trial undoes it at once.
2. With no trial running, a success keeps everything. A failure looks up the approach's diagnosis table for the outcome and starts a trial of the first knob that is free, has a step
   left inside its bounds and was not undone recently. An `ask` knob is not changed: it becomes a suggestion in the report. A `fixed` knob is skipped.

One knob changes at a time, by one step. Results are counted per conditions (attachment + floor + the approach's own), so what works on hardwood is not carried to tile.
Every decision carries a first-person note built from the numbers and the attempt numbers behind it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .approach import Outcome
from .spec import Knob

TRIAL_N = 2                    # attempts with a change before it is judged
TRIAL_MAX = 3                  # ... at most, when the first two are too close to call
BASELINE_N = 3                 # attempts before the change it is compared with
MARGIN = 0.05                  # a change must beat the baseline by this much (scores are 0 to 1) to be kept
CLOSE = 0.05                   # within this of the baseline after TRIAL_N: one more attempt
RETRY_AFTER = 30               # an undone value may be tried again after this many more attempts


@dataclass
class Decision:
    action: str                # "keep" | "try" | "wait" | "kept" | "undo" | "suggest" | "none" | "not_counted"
    note: str
    knob: str | None = None
    old: object = None
    new: object = None
    evidence: list = field(default_factory=list)       # attempt numbers

    def as_dict(self) -> dict:
        return {"action": self.action, "note": self.note, "knob": self.knob, "old": self.old, "new": self.new, "evidence": self.evidence}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _good(scores, threshold=0.5):
    return sum(1 for s in scores if s >= threshold)


class Judge:
    """`state` is this goal's record for one set of conditions (journal.State keeps it on disk). `knobs` already carry the goal's controls."""

    def __init__(self, knobs: list[Knob], diagnosis: dict, state: dict | None = None):
        self.knobs = {k.name: k for k in knobs}
        self.diagnosis = diagnosis
        self.state = state if state is not None else {}
        st = self.state
        st.setdefault("settings", {})          # the free and ask knobs as G2 has them now (ask knobs only change when the user changes them)
        st.setdefault("trial", None)
        st.setdefault("history", [])           # [attempt number, score] under the current settings, newest last
        st.setdefault("rejected", {})          # "knob=value" -> the attempt count when it was undone
        st.setdefault("values", {})            # "knob=value" -> [attempts, score sum]: what each tried value scored
        st.setdefault("count", 0)              # counted attempts under these conditions
        st.setdefault("suggestions", {})       # knob -> {"new", "because", "evidence"}

    # ------------------------------------------------------------------------------------------------ settings
    def settings(self, base: dict) -> dict:
        """The settings for the next attempt: the user's own (`base`) with G2's learned values for the free knobs on top. Ask and fixed knobs always come from `base`."""
        out = dict(base)
        for name, v in self.state["settings"].items():
            k = self.knobs.get(name)
            if k is None or k.control != "free":
                continue
            try:
                out[name] = k.check(v)
            except ValueError:
                continue
        return out

    def _say(self, name: str, v) -> str:
        k = self.knobs[name]
        return f"{k.says()} {k.show(v)}"

    # ------------------------------------------------------------------------------------------------ one attempt
    def update(self, n: int, outcome: Outcome, used: dict) -> list[Decision]:
        """Judge attempt number `n` (its outcome, the settings it used). Returns the decisions, in order; the next attempt's settings are then `settings(base)`."""
        st = self.state
        if not outcome.counted:
            return [Decision("not_counted", f"Attempt {n} is not counted: {outcome.text}.")]
        st["count"] += 1
        out: list[Decision] = []
        tr = st["trial"]
        if tr is not None:
            tr["scores"].append(outcome.score)
            tr["attempts"].append(n)
            self._count_value(tr["knob"], tr["new"], outcome.score)
            d = self._judge_trial(n, outcome)
            out.append(d)
            if d.action == "wait":
                return out
        else:
            st["history"] = (st["history"] + [[n, outcome.score]])[-BASELINE_N:]
            for name in self.knobs:                                              # what the values in use scored (the free knobs only)
                if self.knobs[name].control == "free" and name in used:
                    self._count_value(name, used[name], outcome.score)
        if outcome.success:
            if not out:
                out.append(Decision("keep", f"Attempt {n}: {outcome.text}. That worked, so the same again.", evidence=[n]))
            return out
        if outcome.fell:
            out.append(Decision("none", f"Attempt {n}: {outcome.text}. The session ends here.", evidence=[n]))
            return out
        out.append(self._next_change(n, outcome, used))
        return out

    def _count_value(self, name, value, score):
        key = f"{name}={value}"
        c = self.state["values"].setdefault(key, [0, 0.0])
        c[0] += 1
        c[1] = round(c[1] + float(score), 4)

    def _judge_trial(self, n: int, outcome: Outcome) -> Decision:
        st = self.state
        tr = st["trial"]
        name, old, new = tr["knob"], tr["old"], tr["new"]
        base = [s for _a, s in tr["baseline"]]
        mb, mt = _mean(base), _mean(tr["scores"])
        ev = [a for a, _s in tr["baseline"]] + tr["attempts"]
        line = f"{_good(tr['scores'])} of {len(tr['scores'])} good with it, {_good(base)} of {len(base)} before (scores {mt:.2f} against {mb:.2f})"
        if outcome.fell:
            return self._undo(n, f"I fell trying {self._say(name, new)}: back to {self._say(name, old)}.", ev)
        if len(tr["scores"]) < TRIAL_N:
            return Decision("wait", f"Attempt {n}: {outcome.text}. Still trying {self._say(name, new)} ({len(tr['scores'])} of {TRIAL_N} attempts).", name, old, new, ev)
        if mt > mb + MARGIN:
            st["settings"][name] = new
            st["history"] = [[a, s] for a, s in zip(tr["attempts"], tr["scores"])][-BASELINE_N:]
            st["trial"] = None
            return Decision("kept", f"{_cap(self._say(name, new))} works better than {self.knobs[name].show(old)}: {line}. I'm keeping it.", name, old, new, ev)
        if abs(mt - mb) <= CLOSE and len(tr["scores"]) < TRIAL_MAX:
            return Decision("wait", f"Attempt {n}: {outcome.text}. {_cap(self._say(name, new))} is too close to call so far ({line}): one more attempt with it.",
                            name, old, new, ev)
        return self._undo(n, f"{_cap(self._say(name, new))} didn't help ({line}): back to {self.knobs[name].show(old)}.", ev)

    def _undo(self, n: int, note: str, ev: list) -> Decision:
        st = self.state
        tr = st["trial"]
        st["settings"][tr["knob"]] = tr["old"]
        st["rejected"][f"{tr['knob']}={tr['new']}"] = st["count"]
        st["trial"] = None
        return Decision("undo", note, tr["knob"], tr["old"], tr["new"], ev)

    def _recently_rejected(self, name, value) -> bool:
        at = self.state["rejected"].get(f"{name}={value}")
        return at is not None and self.state["count"] - at < RETRY_AFTER

    def _choice(self, k: Knob, current):
        """Another option of a choice knob: one never tried first (in the knob's order), else the best scoring, never one undone recently."""
        vals = self.state["values"]
        cands = [o for o in k.options if o != current and not self._recently_rejected(k.name, o)]
        if not cands:
            return None
        untried = [o for o in cands if f"{k.name}={o}" not in vals]
        if untried:
            return untried[0]
        return max(cands, key=lambda o: vals[f"{k.name}={o}"][1] / max(1, vals[f"{k.name}={o}"][0]))

    def _next_change(self, n: int, outcome: Outcome, used: dict) -> Decision:
        st = self.state
        suggestion = None
        for name, direction in self.diagnosis.get(outcome.code, []):
            k = self.knobs.get(name)
            if k is None or name not in used or k.control == "fixed":
                continue
            cur = st["settings"].get(name, used[name]) if k.control == "free" else used[name]      # after an undo, step from the value restored, not the one just tried
            new = self._choice(k, cur) if direction == "other" else k.stepped(cur, direction)
            if new is None or new == cur or self._recently_rejected(name, new):
                continue
            if k.control == "ask":
                prev = st["suggestions"].get(name) or {}
                status = prev.get("status", "new") if prev.get("new") == new else "new"          # the same suggestion again keeps its answer ("review" is not asked twice)
                st["suggestions"][name] = {"new": new, "old": cur, "because": outcome.text, "evidence": sorted(set(prev.get("evidence", []) + [n])) if prev.get("new") == new else [n],
                                           "status": status}
                suggestion = suggestion or Decision("suggest", f"I think {self._say(name, new)} would help, but that one is yours to change.", name, cur, new, [n])
                continue
            st["trial"] = {"knob": name, "old": cur, "new": new, "baseline": list(st["history"])[-BASELINE_N:], "scores": [], "attempts": [], "why": outcome.code, "started_at": n}
            st["settings"][name] = new
            extra = f" ({suggestion.note})" if suggestion else ""
            return Decision("try", f"Attempt {n}: {outcome.text}. Next I'll try {self._say(name, new)} instead of {k.show(cur)}.{extra}", name, cur, new, [n])
        if suggestion is not None:
            suggestion.note = f"Attempt {n}: {outcome.text}. " + suggestion.note
            return suggestion
        return Decision("none", f"Attempt {n}: {outcome.text}. I have nothing left to change for this right now.", evidence=[n])
