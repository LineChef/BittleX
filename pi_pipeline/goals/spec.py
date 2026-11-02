"""Goals and the settings G2 may change (goals plan, 2026-10-31).

A Knob is one setting an approach exposes. Its `control` says who may change it:

  free    G2 changes it on his own, one step at a time, inside its bounds (the default: user, 2026-10-31)
  ask     G2 may conclude it should change; he only says so in the report, the user changes it
  fixed   the user or the code sets it; G2 never touches it

A Goal is what the user sets: which approach, the budget of a session and any change to a knob's control. Two kinds (user, 2026-10-31):

  task      an episode with a start, a success and an end, pursued one at a time ("punt the ball"); started by its phrase or chosen by "G2, practise"
  standing  always on, no start or end ("turn away from walls"); every encounter in any activity is an attempt; never chosen, it runs inside every task as a limit

`priority` (in goals.json, highest first) orders them: a standing goal ranked above a task limits that task (walls above the punt: he never chases the ball closer to a wall
than the wall goal allows), and "G2, practise" weighs tasks by it. Goals live in `~/.local/share/g2/goals.json` (G2_GOALS moves it); the
built-in goals below are used when the file does not name them. Only the user sets goals (user, 2026-10-31).
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field, replace

CONTROLS = ("free", "ask", "fixed")
GOALS_PATH = "~/.local/share/g2/goals.json"


@dataclass(frozen=True)
class Knob:
    name: str
    kind: str                         # "float" | "int" | "bool" | "choice"
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    options: tuple = ()
    control: str = "free"
    label: str = ""                   # how a note names it ("punching from")
    unit: str = ""                    # "in", "deg", "s" or ""

    def check(self, value):
        """The value if it is allowed, else ValueError."""
        if self.kind == "choice":
            if value not in self.options:
                raise ValueError(f"{self.name} must be one of {', '.join(map(str, self.options))}")
            return value
        if self.kind == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"{self.name} must be true or false")
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(float(value)):
            raise ValueError(f"{self.name} must be a number")
        v = int(value) if self.kind == "int" else float(value)
        if (self.lo is not None and v < self.lo - 1e-9) or (self.hi is not None and v > self.hi + 1e-9):
            raise ValueError(f"{self.name} must be between {self.lo} and {self.hi}")
        return v

    def stepped(self, value, direction: int):
        """`value` moved one step in `direction` (+1 / -1), or None when that leaves the bounds or the knob has no step."""
        if self.kind not in ("float", "int") or not self.step or direction not in (1, -1):
            return None
        v = float(value) + direction * float(self.step)
        v = int(round(v)) if self.kind == "int" else round(v, 3)
        try:
            return self.check(v)
        except ValueError:
            return None

    def show(self, value) -> str:
        if self.kind == "float":
            return f"{float(value):g}{(' ' + self.unit) if self.unit else ''}"
        if self.kind == "int":
            return f"{int(value)}{(' ' + self.unit) if self.unit else ''}"
        return str(value)

    def says(self) -> str:
        return self.label or self.name.replace("_", " ")


@dataclass(frozen=True)
class Goal:
    id: str
    title: str
    approach: str
    attempts: int = 10                # attempts per session (user, 2026-10-31)
    minutes: float = 20.0             # a session never runs longer
    min_pack_pct: int = 30            # no attempt starts below this pack % (and never past the battery gate)
    target_successes: int | None = None      # end the session early after this many successes (None: use every attempt)
    rest_between_s: float = 2.0       # standing still between attempts (was 5: standing still is what lets the legs go, 2026-11-02)
    controls: dict = field(default_factory=dict)       # knob name -> free / ask / fixed, the user's changes to the approach's defaults
    start_words: tuple = ()           # the spoken start phrases ("G2, ball goal")
    kind: str = "task"                # "task" | "standing"
    needs_attachment: str | None = None      # the attachment it needs ("arm" for the punt): "G2, practise" skips it otherwise
    practice_words: tuple = ()        # words that name it in "G2, practise <words>"
    practice_say: str = ""            # how he names it in "I'll practise ...": "punting the ball"

    def control_of(self, knob: Knob) -> str:
        c = self.controls.get(knob.name, knob.control)
        return c if c in CONTROLS else knob.control

    def knobs(self, knobs: list[Knob]) -> list[Knob]:
        """The approach's knobs with the user's controls applied."""
        return [replace(k, control=self.control_of(k)) for k in knobs]


BUILTIN = {
    "ball_punt": Goal("ball_punt", "Punt the ball", "ball_punt", attempts=10, minutes=20.0, min_pack_pct=30, target_successes=None,
                      start_words=("ball goal", "punt goal", "start the ball goal", "start the punt goal", "goal attempt", "start a goal attempt"),
                      needs_attachment="arm", practice_words=("ball", "punt", "punting", "the ball", "the punt"), practice_say="punting the ball"),
    "walls": Goal("walls", "Turn away from walls", "walls", kind="standing", attempts=0, minutes=5.0, min_pack_pct=30,
                  practice_words=("walls", "wall", "the walls", "turning", "turning away"), practice_say="turning away from walls"),
}
DEFAULT_PRIORITY = ("walls", "ball_punt")        # walls above the punt (user, 2026-10-31: always turn away from a wall, also while chasing the ball)


def path() -> str:
    return os.path.expanduser(os.environ.get("G2_GOALS", GOALS_PATH))


def _from_dict(gid: str, d: dict, base: Goal | None) -> Goal:
    known = {f for f in Goal.__dataclass_fields__}
    vals = {k: v for k, v in d.items() if k in known and k != "id"}
    for tup in ("start_words", "practice_words"):
        if tup in vals:
            vals[tup] = tuple(vals[tup])
    if base is not None:
        return replace(base, **vals)
    return Goal(id=gid, **vals)


def load(p: str | None = None) -> tuple[dict[str, Goal], list[str]]:
    """(goal id -> Goal, problems). The built-in goals, with the file's entries applied on top."""
    goals = dict(BUILTIN)
    problems = []
    p = p or path()
    try:
        raw = json.load(open(p))
    except FileNotFoundError:
        return goals, problems
    except (OSError, ValueError) as e:
        return goals, [f"{p} could not be read ({e}): the built-in goals are used"]
    for gid, d in (raw.get("goals") or {}).items():
        try:
            goals[gid] = _from_dict(gid, d, goals.get(gid))
        except TypeError as e:
            problems.append(f"goal {gid!r} ignored: {e}")
    return goals, problems


def save_goal(goal: Goal, p: str | None = None) -> None:
    p = p or path()
    try:
        raw = json.load(open(p))
    except (OSError, ValueError):
        raw = {}
    d = asdict(goal)
    d.pop("id")
    d["start_words"] = list(goal.start_words)
    d["practice_words"] = list(goal.practice_words)
    raw.setdefault("goals", {})[goal.id] = d
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(json.dumps(raw, indent=2) + "\n")


def priority(p: str | None = None) -> list[str]:
    """The goal ids, highest priority first: goals.json's "priority" list, then any goal it leaves out (built-in order)."""
    goals, _ = load(p)
    try:
        raw = json.load(open(p or path())).get("priority") or []
    except (OSError, ValueError, AttributeError):
        raw = []
    order = [g for g in raw if g in goals] or [g for g in DEFAULT_PRIORITY if g in goals]
    return order + [g for g in goals if g not in order]


def set_priority(order: list[str], p: str | None = None) -> list[str]:
    p = p or path()
    try:
        raw = json.load(open(p))
    except (OSError, ValueError):
        raw = {}
    raw["priority"] = list(order)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w") as f:
        f.write(json.dumps(raw, indent=2) + "\n")
    return priority(p)


def ranks_above(a: str, b: str, p: str | None = None) -> bool:
    order = priority(p)
    return a in order and b in order and order.index(a) < order.index(b)


def goal_for_words(text_normalized: str, goals: dict[str, Goal] | None = None) -> Goal | None:
    """The goal whose start phrase is the whole (normalised) utterance, or starts it."""
    goals = goals if goals is not None else load()[0]
    for g in goals.values():
        for w in g.start_words:
            if text_normalized == w or text_normalized.startswith(w + " "):
                return g
    return None
