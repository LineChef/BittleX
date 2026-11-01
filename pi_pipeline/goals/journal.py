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


def current_conditions(extra: dict | None = None) -> dict:
    """The shared conditions (attachment, floor) plus the approach's own."""
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


class State:
    def __init__(self, path: str | None = None):
        self.path = path or state_path()
        try:
            self.data = json.load(open(self.path))
        except (OSError, ValueError):
            self.data = {}

    def for_goal(self, goal: str, cond_key: str) -> dict:
        return self.data.setdefault(goal, {}).setdefault(cond_key, {})

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            f.write(json.dumps(self.data, indent=1, default=str) + "\n")
        os.replace(tmp, self.path)

    def reset(self, goal: str) -> bool:
        had = goal in self.data
        self.data.pop(goal, None)
        self.save()
        return had


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
