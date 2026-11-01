"""How G2 judges his attempts, on the Pi with no API call (goals plan, "How G2 judges an attempt"). Shared by every goal. Rebuilt 2026-10-31 after an offline test showed the
first version mostly got stuck (it judged a change on 2 or 3 attempts and then banned the step it undid).

1. **Every attempt counts, for every value tried.** Per knob and value: attempts, hits, score sum, kept per conditions (attachment + floor) across sessions.
2. **Each knob is judged by its own stage.** The approach maps knobs to stages (search, approach, align, punch for the ball) and the outcome scores each stage it reached,
   so a search setting is not blamed for a missed punch and a punch setting gets no record from an attempt that never punched.
3. **Failures vote for a direction.** The approach's diagnosis table turns an outcome into the knobs it points at and which way ("missed" -> punch from closer). The votes
   are counted at the value in use.
4. **One knob at a time: the focus,** the free knob recent failures point at most. The others stay at their best-supported value.
5. **The next value is chosen by evidence with some exploration** (Thompson sampling): among the current value and the neighbour the votes point to (both neighbours with no
   lean; every option for a choice knob), each draws a hit rate from its record and the highest draw is used. A value with a good record is chosen most of the time; an
   untried neighbour still gets a chance; a move is never more than one step.
6. **What he keeps is the best-supported value** (the best record with at least MIN_TRIES attempts), not the last one tried. A session starts from those.
7. **A fall** while trying a value that is not his best bans that value for RETRY_AFTER attempts.
8. **A settled setting is left alone** (added 2026-10-31): when its best value has SETTLE_N attempts and every allowed neighbour has SETTLE_NEIGHBOUR_N and a record clearly worse
   (by SETTLE_MARGIN), the focus moves on to the next setting the failures point at. It is unsettled again when 3 of the last 4 attempts at its best value fail.
9. **New conditions start from his best elsewhere** (a new floor or a hardware change, `begin_session(prior=...)`): the starting values, not the records, so old evidence never
   holds him at an old answer after the hardware changes.

Plain "G2, punt" attempts add to the records too (`observe`: nothing is changed), and an attempt the user marks wrong is taken out again (`retract`).

The user's overrides (goals/overrides.py) sit on top: a pinned knob is held at the user's value, a limit keeps every choice inside the user's range, an undone value is banned.
Ask knobs are never changed: a failure that points at one becomes a suggestion. Fixed knobs are never touched.

`tests/test_goals.py` keeps a made-up world with a known best value as a permanent check: after 30 attempts the judge must end within one step of the best in at least
85% of runs.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .approach import Outcome
from .spec import Knob

HIT = 0.5                      # a stage score at or above this counts as a hit
MIN_TRIES = 2                  # attempts before a value can be called the best
RETRY_AFTER = 30               # a value banned after a fall may be tried again after this many more attempts
PRESSURE_DECAY = 0.8           # how fast old failures stop counting toward the focus
PRESSURE_WEIGHTS = (1.0, 0.5, 0.25)      # the first, second and third knob an outcome points at
SETTLE_N = 5                   # attempts at the best value before a setting can be settled
SETTLE_NEIGHBOUR_N = 3         # ... and at each neighbour
SETTLE_MARGIN = 0.15           # ... whose record must be at least this much worse
RECENT_N = 6                   # how many recent results each value keeps (to notice a settled value going bad)


@dataclass
class Decision:
    action: str                # "keep" | "try" | "kept" | "undo" | "suggest" | "none" | "not_counted"
    note: str
    knob: str | None = None
    old: object = None
    new: object = None
    evidence: list = field(default_factory=list)       # attempt numbers

    def as_dict(self) -> dict:
        return {"action": self.action, "note": self.note, "knob": self.knob, "old": self.old, "new": self.new, "evidence": self.evidence}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def vkey(value) -> str:
    """The record key of a value (JSON keys are strings)."""
    if isinstance(value, bool) or isinstance(value, str):
        return str(value)
    if isinstance(value, (int, float)):
        return str(round(float(value), 4))
    return str(value)


class Judge:
    """`state`: this goal's record for one set of conditions (journal.State keeps it on disk). `knobs` carry the goal's controls. `stage_of`: knob -> stage name
    (missing: the whole attempt's score). `overrides`: {"pins": {knob: value}, "limits": {knob: [lo, hi]}, "banned": {knob: {vkey: None}}} (goals/overrides.py)."""

    def __init__(self, knobs: list[Knob], diagnosis: dict, state: dict | None = None, *, stage_of: dict | None = None, overrides: dict | None = None, rng=None):
        self.knobs = {k.name: k for k in knobs}
        self.diagnosis = diagnosis
        self.stage_of = stage_of or {}
        self.ov = overrides or {}
        self.rng = rng or random.Random()
        self.state = state if state is not None else {}
        st = self.state
        st.setdefault("values", {})            # knob -> {vkey: {"v", "n", "hits", "sum", "down", "up", "last"}}
        st.setdefault("current", {})           # knob -> the value the next attempt uses (free knobs)
        st.setdefault("pressure", {})          # knob -> decayed count of failures pointing at it
        st.setdefault("focus", None)
        st.setdefault("count", 0)              # counted attempts under these conditions
        st.setdefault("banned", {})            # knob -> {vkey: count when banned} (after a fall)
        st.setdefault("suggestions", {})       # knob -> {"new", "old", "because", "evidence", "status"}
        st.setdefault("settled", [])           # knobs left alone: their best value clearly beats its neighbours
        self._start_best = None
        self.started_from = None

    # ------------------------------------------------------------------------------------------------ records
    def record(self, name: str, value) -> dict | None:
        return self.state["values"].get(name, {}).get(vkey(value))

    def _rec(self, name: str, value) -> dict:
        return self.state["values"].setdefault(name, {}).setdefault(vkey(value), {"v": value, "n": 0, "hits": 0, "sum": 0.0, "down": 0, "up": 0, "last": 0, "recent": []})

    def says(self, name: str, value) -> str:
        r = self.record(name, value)
        k = self.knobs[name]
        tail = f" ({r['hits']} of {r['n']} good)" if r and r["n"] else " (not tried yet)"
        return f"{k.says()} {k.show(value)}{tail}"

    @staticmethod
    def _mean(r) -> float:
        return (r["hits"] + 1) / (r["n"] + 2)

    def best(self, name: str, fallback):
        """The best-supported value: the best record (hits, with one imagined hit and one imagined miss) among values tried MIN_TRIES times and still allowed;
        `fallback` when none is, or when its own record is as good."""
        tried = [r for r in self.state["values"].get(name, {}).values() if r["n"] >= MIN_TRIES and self._allowed(name, r["v"])]
        if not tried:
            return fallback if self._allowed(name, fallback) else self._clamp_to_limits(name, fallback)
        top = max(tried, key=lambda r: (self._mean(r), r["n"]))
        fb = self.record(name, fallback)
        if fb is not None and fb["n"] >= MIN_TRIES and self._allowed(name, fallback) and self._mean(fb) >= self._mean(top):
            return fallback
        return top["v"]

    # ------------------------------------------------------------------------------------------------ overrides
    def _banned(self, name: str, value) -> bool:
        k = vkey(value)
        if k in ((self.ov.get("banned") or {}).get(name) or {}):
            return True                                                             # the user undid it
        at = (self.state["banned"].get(name) or {}).get(k)
        return at is not None and self.state["count"] - at < RETRY_AFTER

    def _in_limits(self, name: str, value) -> bool:
        lim = (self.ov.get("limits") or {}).get(name)
        if not lim or isinstance(value, (str, bool)):
            return True
        return lim[0] - 1e-9 <= float(value) <= lim[1] + 1e-9

    def _allowed(self, name: str, value) -> bool:
        k = self.knobs.get(name)
        if k is None:
            return False
        try:
            k.check(value)
        except ValueError:
            return False
        return self._in_limits(name, value) and not self._banned(name, value)

    def _clamp_to_limits(self, name: str, value):
        lim = (self.ov.get("limits") or {}).get(name)
        k = self.knobs[name]
        if not lim or k.kind not in ("float", "int"):
            return value
        v = min(max(float(value), lim[0]), lim[1])
        if k.step:                                                                  # onto the knob's own steps inside the limits
            lo = k.lo if k.lo is not None else 0.0
            v = lo + round((v - lo) / k.step) * k.step
            v = min(max(v, lim[0]), lim[1])
        return int(round(v)) if k.kind == "int" else round(v, 3)

    def pinned(self, name: str):
        pins = self.ov.get("pins") or {}
        return pins.get(name), name in pins

    def _free(self, name: str) -> bool:
        k = self.knobs.get(name)
        return k is not None and k.control == "free" and not self.pinned(name)[1]

    # ------------------------------------------------------------------------------------------------ settings
    def settings(self, base: dict) -> dict:
        """The next attempt's settings: the user's own (`base`), G2's values for the free knobs, the user's pins and limits on top."""
        out = dict(base)
        for name, k in self.knobs.items():
            if name not in out:
                continue
            if k.control == "free":
                v = self.state["current"].get(name)
                if v is None or not self._allowed(name, v):
                    v = self.best(name, out[name])
                out[name] = self._clamp_to_limits(name, v)
            pv, has = self.pinned(name)
            if has:
                try:
                    out[name] = k.check(pv)
                except ValueError:
                    pass
        return out

    def begin_session(self, base: dict, prior: dict | None = None, prior_from: str | None = None) -> dict:
        """Start a session from the best-supported values (not where the last session's exploration stopped). A knob with no record under these conditions starts
        from `prior` (his best values under other conditions: another floor, the previous hardware) when given, else from `base`. Returns the first attempt's settings."""
        used_prior = False
        for name, k in self.knobs.items():
            if k.control == "free" and name in base:
                start = base[name]
                if prior and name in prior and not any(r["n"] for r in (self.state["values"].get(name) or {}).values()) and self._allowed(name, prior[name]):
                    start, used_prior = prior[name], True
                self.state["current"][name] = self.best(name, start)
        self.started_from = prior_from if used_prior else None
        self._start_best = {n: self.state["current"][n] for n, k in self.knobs.items() if k.control == "free" and n in base}
        return self.settings(base)

    # ------------------------------------------------------------------------------------------------ one attempt
    def _stage_score(self, name: str, outcome: Outcome):
        stage = self.stage_of.get(name)
        stages = getattr(outcome, "stages", None)
        if stage is None or stages is None:
            return outcome.score
        return stages.get(stage)

    def _learn(self, n: int, outcome: Outcome, used: dict, sign: int = 1):
        """Steps 1 and 2: the records (each knob by its own stage) and a failure's direction votes and pressure. `sign` -1 takes an attempt back out. Returns a suggestion
        Decision for an ask knob, or None."""
        st = self.state
        for name, k in self.knobs.items():
            if name not in used or k.control != "free":
                continue
            s = self._stage_score(name, outcome)
            if s is None:
                continue                                                        # its stage was not reached: no evidence either way
            r = self._rec(name, used[name])
            hit = int(s >= HIT)
            r["n"] = max(0, r["n"] + sign)
            r["hits"] = max(0, min(r["n"], r["hits"] + sign * hit))
            r["sum"] = round(max(0.0, r["sum"] + sign * float(s)), 4)
            if sign > 0:
                r["last"] = n
                r["recent"] = (r.get("recent", []) + [hit])[-RECENT_N:]
            elif r.get("recent"):
                r["recent"] = r["recent"][:-1]
        if sign > 0:
            for name in list(st["pressure"]):
                st["pressure"][name] = round(st["pressure"][name] * PRESSURE_DECAY, 4)
        suggestion = None
        if not outcome.success:
            w = 0
            for name, direction in self.diagnosis.get(outcome.code, []):
                k = self.knobs.get(name)
                if k is None or name not in used:
                    continue
                if k.control == "ask":
                    if sign < 0:
                        continue
                    new = k.stepped(used[name], direction) if direction in (1, -1) else None
                    if new is not None and not self._banned(name, new):
                        prev = st["suggestions"].get(name) or {}
                        same = prev.get("new") == new
                        st["suggestions"][name] = {"new": new, "old": used[name], "because": outcome.text,
                                                   "evidence": sorted(set(prev.get("evidence", []) + [n])) if same else [n],
                                                   "status": prev.get("status", "new") if same else "new"}
                        suggestion = suggestion or Decision("suggest", f"I think {k.says()} {k.show(new)} would help, but that one is yours to change.", name, used[name], new, [n])
                    continue
                if not self._free(name):
                    continue
                if direction in (1, -1):
                    r = self._rec(name, used[name])
                    key = "down" if direction < 0 else "up"
                    r[key] = max(0, r[key] + sign)
                if w < len(PRESSURE_WEIGHTS) and sign > 0:
                    st["pressure"][name] = round(st["pressure"].get(name, 0.0) + PRESSURE_WEIGHTS[w], 4)
                    w += 1
        return suggestion

    def observe(self, n: int, outcome: Outcome, used: dict) -> list[Decision]:
        """An attempt made outside a goal session (a plain "G2, punt"): it adds to the records and the votes; no setting is changed."""
        if not outcome.counted:
            return [Decision("not_counted", f"Attempt {n} is not counted: {outcome.text}.")]
        self.state["count"] += 1
        self._learn(n, outcome, used)
        self._update_settled()
        return [Decision("none", f"Attempt {n} (a plain punt, counted, nothing changed): {outcome.text}.", evidence=[n])]

    def retract(self, outcome: Outcome, used: dict) -> None:
        """Take an attempt the user marked wrong back out of the records and votes."""
        if outcome.counted:
            self._learn(0, outcome, used, sign=-1)
            self.state["count"] = max(0, self.state["count"] - 1)
            self._update_settled()

    def _neighbours(self, name: str, value) -> list:
        k = self.knobs[name]
        if k.kind == "choice":
            return [o for o in k.options if o != value and self._allowed(name, o)]
        return [v for v in (k.stepped(value, -1), k.stepped(value, 1)) if v is not None and self._allowed(name, v)]

    def is_settled(self, name: str) -> bool:
        k = self.knobs.get(name)
        if k is None or not self._free(name):
            return False
        cur = self.state["current"].get(name)
        if cur is None:
            return False
        b = self.best(name, cur)
        r = self.record(name, b)
        if r is None or r["n"] < SETTLE_N:
            return False
        recent = r.get("recent", [])[-4:]
        if len(recent) >= 4 and recent.count(0) >= 3:
            return False                                                      # his best has started failing: look again
        for v in self._neighbours(name, b):
            rn = self.record(name, v)
            if rn is None or rn["n"] < SETTLE_NEIGHBOUR_N or self._mean(rn) > self._mean(r) - SETTLE_MARGIN:
                return False
        return True

    def _update_settled(self) -> list[str]:
        """The settled list; returns the knobs that settled just now."""
        before = set(self.state["settled"])
        now = [name for name in self.knobs if self.is_settled(name)]
        self.state["settled"] = now
        return [x for x in now if x not in before]

    def update(self, n: int, outcome: Outcome, used: dict) -> list[Decision]:
        """Judge attempt number `n` (its outcome and the settings it used) and set the next attempt's values. Returns the decisions, in order."""
        st = self.state
        if not outcome.counted:
            return [Decision("not_counted", f"Attempt {n} is not counted: {outcome.text}.")]
        st["count"] += 1
        out: list[Decision] = []
        suggestion = self._learn(n, outcome, used)
        for name in self._update_settled():
            k = self.knobs[name]
            b = self.best(name, used.get(name))
            r = self.record(name, b)
            out.append(Decision("kept", f"{_cap(k.says())} {k.show(b)} has settled: {r['hits']} of {r['n']} good, clearly better than the values next to it. I'll leave it there.", name, None, b, [n]))
        # 3. a fall while trying a value that is not his best bans that value for a while
        focus = st["focus"]
        if outcome.fell and focus and focus in used and self._free(focus):
            b = self.best(focus, used[focus])
            if used[focus] != b:
                st["banned"].setdefault(focus, {})[vkey(used[focus])] = st["count"]
                st["current"][focus] = b
                k = self.knobs[focus]
                out.append(Decision("undo", f"I fell trying {k.says()} {k.show(used[focus])}: back to {k.show(b)}, and I won't try that again for a while.", focus, used[focus], b, [n]))
        if outcome.fell:
            out.append(Decision("none", f"Attempt {n}: {outcome.text}. The session ends here.", evidence=[n]))
            return out
        # 4. the focus: the free knob recent failures point at most (it changes only on a clear lead)
        settled = set(st["settled"])
        cands = [(p, name) for name, p in st["pressure"].items() if p > 0.05 and self._free(name) and name in used and name not in settled]
        if focus in settled:
            focus = None
        if cands:
            top = max(cands)[1]
            if focus is None or not self._free(focus) or focus not in used or st["pressure"].get(top, 0.0) > st["pressure"].get(focus, 0.0) + 0.25:
                focus = top
        st["focus"] = focus
        for name in self.knobs:                                                    # every knob but the focus uses its best-supported value
            if name != focus and self._free(name) and name in used:
                st["current"][name] = self.best(name, used[name])
        if focus is None or not self._free(focus) or focus not in used:
            out.append(Decision("keep", f"Attempt {n}: {outcome.text}. " + ("That worked, so the same again." if outcome.success else "Nothing to change for that yet."), evidence=[n]))
            if suggestion:
                out.append(suggestion)
            return out
        # 5. the focus knob's next value, by evidence with some exploration
        cur = used[focus]
        nxt, lean = self._choose(focus, cur)
        st["current"][focus] = nxt
        k = self.knobs[focus]
        if nxt == cur:
            out.append(Decision("keep", f"Attempt {n}: {outcome.text}. Same again: {self.says(focus, nxt)}.{lean}", focus, cur, nxt, [n]))
        else:
            r = self.record(focus, cur)
            was = f" ({r['hits']} of {r['n']} good)" if r and r["n"] else ""
            out.append(Decision("try", f"Attempt {n}: {outcome.text}. Next: {self.says(focus, nxt)} instead of {k.show(cur)}{was}.{lean}", focus, cur, nxt, [n]))
        if suggestion:
            out.append(suggestion)
        return out

    def _choose(self, name: str, cur) -> tuple[object, str]:
        """Thompson sampling among the current value and the allowed neighbour(s) the votes point to (every allowed option for a choice knob)."""
        k = self.knobs[name]
        lean = ""
        if k.kind == "choice":
            cands = [o for o in k.options if self._allowed(name, o)]
        else:
            r = self.record(name, cur) or {"down": 0, "up": 0}
            dirs = [d for d, ok in ((-1, r["down"] >= r["up"]), (1, r["up"] >= r["down"])) if ok]
            cands = [cur] + [v for v in (k.stepped(cur, d) for d in dirs) if v is not None]
            cands = [c for c in cands if self._allowed(name, c)]
            if r["down"] > r["up"]:
                lean = " My misses point lower."
            elif r["up"] > r["down"]:
                lean = " My misses point higher."
        if not cands:
            return self.best(name, cur), lean
        draws = []
        for v in cands:
            rec = self.record(name, v) or {"hits": 0, "n": 0}
            draws.append((self.rng.betavariate(1 + rec["hits"], 1 + rec["n"] - rec["hits"]), cands.index(v), v))
        return max(draws)[2], lean

    # ------------------------------------------------------------------------------------------------ the end of a session
    def finish(self, base: dict, n: int | None = None) -> list[Decision]:
        """What he keeps: each free knob's best-supported value. A "kept" decision for each knob whose best value changed this session (these become the lessons)."""
        out = []
        start = self._start_best or {}
        for name, k in self.knobs.items():
            if k.control != "free" or name not in base:
                continue
            b = self.best(name, base[name])
            self.state["current"][name] = b
            was = start.get(name, base[name])
            if b != was:
                r, r0 = self.record(name, b), self.record(name, was)
                vs = f", against {r0['hits']} of {r0['n']} with {k.show(was)}" if r0 and r0["n"] else ""
                out.append(Decision("kept", f"{_cap(k.says())} {k.show(b)} works best so far: {r['hits']} of {r['n']} good{vs}. I'm keeping it.", name, was, b,
                                    [n] if n else []))
        return out
