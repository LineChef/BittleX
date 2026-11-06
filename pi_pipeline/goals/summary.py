"""One self-knowledge note per goal (user, 2026-11-06), in place of a pile of per-session lessons.

After a goal session the note for that goal and its conditions (attachment, floor, hardware) is rebuilt from what the goal has learned (goal_state.json): how many attempts were good, and for the
settings with the most evidence the value that works best so far with its record (good of tried). It is saved as ONE memory fact (source `goal_summary`, importance 2, never core) that replaces the
previous note of the same goal. Like the old lessons it is only put in front of him when someone asks about the ball, the goal, practice or learning (memory/memory.py). The per-session notes
stay in the journal (decisions); `G2_GOAL_LESSONS=1` saves them as facts again. No API call.
"""
from __future__ import annotations

import os

SOURCE = "goal_summary"
MAX_SETTINGS = 3
MIN_TRIES = 5


def lessons_as_facts() -> bool:
    return os.environ.get("G2_GOAL_LESSONS", "0").strip().lower() in ("1", "on", "true", "yes")


def build_note(title: str, cond: dict | None, state_for_cond: dict | None) -> str:
    """"Punt the ball (hardwood): 62 of 118 attempts good so far. Best known: walk aim in 3.5 (17 of 23 good), ... Still testing: search order." or ""."""
    vals = (state_for_cond or {}).get("values") or {}
    best, tries, good = [], 0, 0
    for knob, rec in vals.items():
        rows = [v for v in rec.values() if v.get("n", 0) > 0]
        if not rows:
            continue
        if not tries:                                                  # every setting saw every counted attempt: any one of them gives the totals
            tries, good = sum(v.get("n", 0) for v in rows), sum(v.get("hits", 0) for v in rows)
        top = max(rows, key=lambda v: (v.get("hits", 0) + 1) / (v.get("n", 0) + 2))          # best by the smoothed rate, so 1 of 1 does not beat 15 of 20
        if top.get("n", 0) >= MIN_TRIES and len(rows) > 1:
            best.append((top["n"], knob, top))
    if not tries:
        return ""
    best.sort(key=lambda b: -b[0])
    where = (cond or {}).get("floor")
    note = f"{title}{f' ({where})' if where else ''}: {good} of {tries} attempts good so far."
    if best:
        note += " Best known: " + ", ".join(f"{k.replace('_', ' ')} {t.get('v')} ({t.get('hits', 0)} of {t.get('n', 0)} good)" for _n, k, t in best[:MAX_SETTINGS]) + "."
    focus = (state_for_cond or {}).get("focus")
    if focus:
        note += f" Still testing: {str(focus).replace('_', ' ')}."
    return note


def save_note(title: str, cond: dict | None, state_for_cond: dict | None, store=None) -> bool:
    """Replace this goal's note in memory with the current one. Never raises."""
    try:
        note = build_note(title, cond, state_for_cond)
        if not note:
            return False
        if store is None:
            from ..config import settings
            from ..memory.store import Store
            store = Store(settings.memory_db_path)
        for f in store.list_facts():
            if f["source"] == SOURCE and f["fact"].startswith(title):
                store.delete_fact(f["id"])
        return bool(store.add_fact(note, importance=2, core=False, source=SOURCE))
    except Exception:  # noqa: BLE001
        return False
