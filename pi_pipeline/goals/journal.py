"""Where goal sessions are written down (goals plan, "Reading the data").

  ~/.local/share/g2/goal_journal.jsonl   one line per event: session_start, attempt (settings, outcome, numbers), decision (with its note and evidence), session_end
  ~/.local/share/g2/goal_state.json      what each goal has learned, per conditions: {goal id: {conditions key: judge state}}

`G2_GOAL_JOURNAL` / `G2_GOAL_STATE` move them. Nothing is deleted: `reset` empties a goal's learned state and the journal keeps the history.
"""
from __future__ import annotations

import json
import os
import time

JOURNAL = "~/.local/share/g2/goal_journal.jsonl"
STATE = "~/.local/share/g2/goal_state.json"
LESSON_SOURCE = "goal_lesson"
MAX_LESSONS = 3


def journal_path() -> str:
    return os.path.expanduser(os.environ.get("G2_GOAL_JOURNAL", JOURNAL))


def state_path() -> str:
    return os.path.expanduser(os.environ.get("G2_GOAL_STATE", STATE))


def conditions_key(cond: dict) -> str:
    return "|".join(f"{k}={cond[k]}" for k in sorted(cond))


def current_hw() -> str:
    """The hardware epoch in force now (telemetry/hardware_epochs.json): a hardware change starts fresh records (user-approved 2026-10-31)."""
    try:
        from ..telemetry.epochs import epoch_at
        e = epoch_at()
        return e["id"] if e else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def parse_key(cond_key: str) -> dict:
    return dict(p.split("=", 1) for p in cond_key.split("|") if "=" in p)


def prior_conditions(goal_state: dict, cond: dict) -> list[str]:
    """Other conditions of the same goal to start a new one from, best first: the same attachment and floor under earlier hardware (newest first), then the same attachment
    and hardware on another floor, then the same attachment anywhere. Only keys with attempts."""
    rows = []
    for key, st in (goal_state or {}).items():
        c = parse_key(key)
        if key == conditions_key(cond) or not st.get("count") or c.get("attachment") != cond.get("attachment"):
            continue
        rank = 0 if c.get("floor") == cond.get("floor") else (1 if c.get("hw") == cond.get("hw") else 2)
        rows.append((rank, -float(st.get("updated", 0)), key))
    return [k for _r, _u, k in sorted(rows)]


def current_conditions(extra: dict | None = None) -> dict:
    """The shared conditions (attachment, floor, hardware epoch) plus the approach's own."""
    cond = {}
    try:
        from ..attachments import current
        cond["attachment"] = current()
    except Exception:  # noqa: BLE001
        cond["attachment"] = "unknown"
    try:
        from ..telemetry.autolog import get_surface
        cond["floor"] = get_surface()
    except Exception:  # noqa: BLE001
        cond["floor"] = "unknown"
    cond["hw"] = current_hw()
    cond.update(extra or {})
    return cond


class Journal:
    def __init__(self, path: str | None = None, clock=time.time):
        self.path = path or journal_path()
        self._clock = clock

    def write(self, kind: str, **fields) -> dict:
        row = {"kind": kind, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._clock())), **fields}
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        return row

    def read(self) -> list[dict]:
        try:
            with open(self.path) as f:
                rows = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
                return rows
        except FileNotFoundError:
            return []

    def sessions(self, goal: str | None = None) -> list[dict]:
        """[{"start": row, "attempts": [...], "decisions": [...], "end": row | None}] in order."""
        out, cur = [], None
        for r in self.read():
            if r["kind"] == "session_start":
                cur = {"start": r, "attempts": [], "decisions": [], "end": None}
                if goal is None or r.get("goal") == goal:
                    out.append(cur)
                continue
            if cur is None or r.get("session") != cur["start"].get("session"):
                continue
            if r["kind"] == "attempt":
                cur["attempts"].append(r)
            elif r["kind"] == "decision":
                cur["decisions"].append(r)
            elif r["kind"] == "session_end":
                cur["end"] = r
        return out


def _read_json(p: str) -> dict:
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return {}


class State:
    """What the goals have learned. Several instances may be open at once (a goal session, and inside its attempts the walls goal), so `save` writes back only the goals this
    instance touched (`for_goal`, `touch`), merged into the file as it is now: one cannot overwrite what another just learned."""

    def __init__(self, path: str | None = None):
        self.path = path or state_path()
        self.data = _read_json(self.path)
        self._touched: set = set()

    def for_goal(self, goal: str, cond_key: str) -> dict:
        self._touched.add(goal)
        return self.data.setdefault(goal, {}).setdefault(cond_key, {})

    def touch(self, goal: str) -> None:
        self._touched.add(goal)

    def save(self) -> None:
        fresh = _read_json(self.path)
        for goal in self._touched:
            if goal in self.data:
                fresh[goal] = self.data[goal]
            else:
                fresh.pop(goal, None)
        for goal, v in fresh.items():                     # see the others' latest too (the judges keep their references to this instance's own goals)
            if goal not in self._touched:
                self.data[goal] = v
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            f.write(json.dumps(fresh, indent=1, default=str) + "\n")
        os.replace(tmp, self.path)

    def reset(self, goal: str) -> bool:
        had = goal in self.data
        self.data.pop(goal, None)
        self._touched.add(goal)
        self.save()
        return had


def next_number(rec: dict) -> int:
    """The next attempt number under one goal and conditions: never reused, also after a verdict took an attempt out (the count goes down, this does not)."""
    return max(int(rec.get("count", 0)), int(rec.get("last_number", 0))) + 1


def lessons_from(decisions: list[dict], goal_title: str) -> list[str]:
    """Up to MAX_LESSONS memory notes from a session's decisions: the changes he kept, then the ones he undid (the ones with evidence behind them)."""
    out = []
    for action in ("kept", "undo"):
        for d in decisions:
            if d.get("action") == action and d.get("note"):
                out.append(f"{goal_title}: {d['note']}")
    return out[:MAX_LESSONS]


def save_lessons(lessons: list[str], store=None) -> int:
    """Save the notes as memory facts (source goal_lesson, importance 2, never core). Returns how many were saved. Never raises."""
    if not lessons:
        return 0
    try:
        if store is None:
            from ..config import settings
            from ..memory.store import Store
            store = Store(settings.memory_db_path)
        n = 0
        for text in lessons:
            if store.add_fact(text, importance=2, core=False, source=LESSON_SOURCE):
                n += 1
        return n
    except Exception:  # noqa: BLE001
        return 0
