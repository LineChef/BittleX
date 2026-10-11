"""Level 2 of reflection: while G2 is idle, one Claude call reads his latest session recaps and writes up to three short notes about his own experience.

    "I keep turning away from walls in the kitchen." / "I rarely get to the foyer." / "I fell down while walking on the rug."

The notes are saved as facts with source "experience" (importance 1 or 2, never core), so they show in the memory review page (`g2pimem`), can be deleted there, and reach Claude's prompt in
the ordinary way when a conversation touches them. They go through the same guard as every fact (no dates, times or routines; `memory/store.py` refuses them) plus a stricter one here: a note
is about G2 himself ("I ..."), never about a person, and never about where or when anyone was.

Modes (`G2_REFLECT`): `off`; `dry` (the default: the call is made and the notes it WOULD save go to `reflections_dry.jsonl` for you to read, nothing is saved); `on` (saved). One call per pass, at
most one pass per `min_interval_s` (the same idle watcher as the memory tidy-up), and only when a recap has not been reflected on yet.

    python -m pi_pipeline.memory reflect            # dry run now
    python -m pi_pipeline.memory reflect --apply    # save the notes
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from ..memory.consolidate import _unsafe, parse_plan
from ..memory.store import Store
from .recap import ExperienceLog, recap_text

log = logging.getLogger("g2.reflect")

MAX_NOTES = 3
MAX_NOTE_CHARS = 160
MAX_RECAPS = 3
SOURCE = "experience"
DRY_LOG = "~/.local/share/g2/reflections_dry.jsonl"

SYSTEM = """You help G2, a small walking robot, reflect on his own exploration. You are given recaps of his latest exploration sessions (counts of what he did and saw), and the notes about \
his own experience he already has. Reply with ONLY a JSON object: {"notes": [{"text": "I ...", "importance": <1-2>}]}
Rules:
- At most 3 notes, and returning none is the normal outcome. Write a note only when it is supported by the recaps: a pattern across sessions, or something clearly notable in one.
- Each note is one short sentence in G2's own voice, starting with "I", about what happened to HIM: what he saw, where he went, what he bumped into, what went wrong or well.
- Never write about people, pets' owners, or where or when anyone was. Never include dates, times of day, days, schedules or routines. Never invent a place, thing or event that is not in the recaps.
- Do not repeat or reword a note he already has. Do not write advice or promises about the future."""


def _clip(text: str, n: int = MAX_NOTE_CHARS) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def validate_notes(plan: dict | None, existing: list[str]) -> list[dict]:
    """The notes of a model reply that pass the guard: first person, short, nothing time-like, not already known."""
    out = []
    raw = (plan or {}).get("notes")
    for n in (raw if isinstance(raw, list) else []):
        if len(out) >= MAX_NOTES:
            break
        try:
            text, imp = str(n["text"]).strip(), max(1, min(2, int(n.get("importance", 1))))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if not text or len(text) > MAX_NOTE_CHARS or _unsafe(text) or not re.match(r"I\b", text):
            continue
        from ..memory.store import NEAR_DUPLICATE, similarity
        if any(similarity(text, e) >= NEAR_DUPLICATE for e in existing + [o["text"] for o in out]):
            continue
        out.append({"text": text, "importance": imp})
    return out


class ExperienceReflector:
    """Same two methods as the memory `Consolidator` (`has_enough_new`, `run`), so it runs in the same idle watcher."""

    def __init__(self, store: Store, llm, experiences: ExperienceLog | None = None, *, mode: str = "dry", usage=None, dry_path: str = DRY_LOG, min_new_sessions: int = 1):
        self.store, self._llm, self._usage = store, llm, usage
        self.experiences = experiences or ExperienceLog()
        self.mode = mode if mode in ("dry", "on") else "dry"
        self._dry_path = Path(os.path.expanduser(dry_path))
        self.min_new_sessions = min_new_sessions

    def _mark(self) -> int:
        return int(self.store.get_meta("reflected_experience_id", "0") or 0)

    def pending(self) -> list[dict]:
        return self.experiences.after(self._mark())

    def has_enough_new(self) -> bool:
        return len(self.pending()) >= self.min_new_sessions

    def own_notes(self) -> list[str]:
        return [f["fact"] for f in self.store.list_facts() if f["source"] == SOURCE]

    def propose(self) -> tuple[list[dict] | None, int, str]:
        """(notes that pass the guard, the newest recap id read, a short note). One model call."""
        rows = self.experiences.read()[-MAX_RECAPS:]
        if not rows:
            return None, self._mark(), "no recaps yet"
        known = self.own_notes()
        payload = {"recaps": [{"session": r.get("id"), "summary": recap_text(r), "details": {k: r.get(k) for k in ("duration_s", "ended_by", "events", "stops", "seen", "rooms", "wall")}} for r in rows],
                   "notes_already_held": known}
        text, usage = self._llm(SYSTEM, json.dumps(payload))
        if self._usage is not None:
            self._usage.record("consolidation", usage)
        plan = parse_plan(text)
        if plan is None:
            return None, self._mark(), "the model's reply was not usable"
        return validate_notes(plan, known), int(rows[-1].get("id", 0)), "ok"

    def run(self, apply: bool = True, force: bool = False) -> dict:
        """The idle watcher calls `run(apply=True)`; whether notes are really saved still depends on the mode ("dry" only logs them). `force=True` (the CLI's --apply) saves in any mode."""
        apply = force or (apply and self.mode == "on")
        notes, upto, note = self.propose()
        if notes is None:
            return {"ok": False, "note": note}
        if apply:
            saved = [n["text"] for n in notes if self.store.add_fact(n["text"], importance=n["importance"], core=False, source=SOURCE)]
            self.store.set_meta("reflected_experience_id", str(upto))
            log.info("reflection: %d note(s) saved", len(saved))
            return {"ok": True, "applied": True, "saved": saved}
        try:
            self._dry_path.parent.mkdir(parents=True, exist_ok=True)
            with self._dry_path.open("a") as f:
                f.write(json.dumps({"date": time.strftime("%Y-%m-%d"), "after_session": upto, "would_save": [n["text"] for n in notes]}) + "\n")
        except OSError:
            log.debug("could not write the dry-run reflections", exc_info=True)
        self.store.set_meta("reflected_experience_id", str(upto))                  # a dry pass counts as read: the next call waits for a NEW session
        log.info("reflection (dry run): %d note(s) would be saved", len(notes))
        return {"ok": True, "applied": False, "would_save": [n["text"] for n in notes]}


def experience_notes(store: Store) -> list[str]:
    """The notes G2 holds about his own experience (what "what have you learned?" reads out)."""
    return [f["fact"] for f in store.list_facts() if f["source"] == SOURCE]
