"""A record of every memory-processing call: the idle tidy-up (consolidation) and the reflection on his own experience.

Two things live here:
  * `MemoryCallGate`: at most ONE such Claude call per session (user, 2026-10-10). Both passes ask the gate before calling; the first gets it, the other waits. The gate opens again when
    someone talks to G2 again (the idle clock drops) or the process restarts (every exploration hand-over restarts the voice service), i.e. the next session.
  * `log_call` / `read_calls` / `summary`: one JSON line per attempt in `~/.local/share/g2/memory_calls.jsonl` (kind, outcome, mode, counts), so how often the calls are made is on record.
    `python -m pi_pipeline.memory calls [--days N]` prints it. The billed request itself is also in the API log (`python -m pi_pipeline.voice.api_log`, sources "consolidate" and "reflect").
Never raises.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter
from pathlib import Path

log = logging.getLogger("g2.memory_calls")

DEFAULT_PATH = "~/.local/share/g2/memory_calls.jsonl"


def calls_path() -> Path:
    return Path(os.path.expanduser(os.environ.get("G2_MEMORY_CALL_LOG", DEFAULT_PATH)))


def log_call(kind: str, outcome: str, **fields) -> None:
    """outcome: "called" (the request was made), "skipped" (not made: the gate or nothing new), "failed" (made, no usable answer / error)."""
    try:
        p = calls_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "pid": os.getpid(), "kind": kind, "outcome": outcome, **fields}, default=str) + "\n")
    except Exception:  # noqa: BLE001
        log.debug("could not write the memory call log", exc_info=True)


def read_calls(days: float | None = None) -> list[dict]:
    out, cutoff = [], None if days is None else time.time() - days * 86400
    try:
        for line in calls_path().read_text().splitlines():
            try:
                d = json.loads(line)
                if cutoff is not None and time.mktime(time.strptime(d["t"], "%Y-%m-%d %H:%M:%S")) < cutoff:
                    continue
                out.append(d)
            except (ValueError, KeyError):
                continue
    except OSError:
        pass
    return out


def summary(days: float | None = 7) -> str:
    rows = read_calls(days)
    if not rows:
        return "no memory-processing calls recorded" + (f" in the last {days:g} days" if days else "")
    c = Counter((r["kind"], r["outcome"]) for r in rows)
    per_day: dict = {}
    for r in rows:
        if r["outcome"] == "called":
            per_day.setdefault(r["t"][:10], Counter())[r["kind"]] += 1
    lines = [f"memory-processing calls{f' in the last {days:g} days' if days else ''}:"]
    for kind in sorted({k for k, _ in c}):
        lines.append(f"  {kind}: {c.get((kind, 'called'), 0)} called, {c.get((kind, 'failed'), 0)} failed, {c.get((kind, 'skipped'), 0)} skipped")
    for day in sorted(per_day):
        lines.append(f"  {day}: " + ", ".join(f"{k} x{n}" for k, n in sorted(per_day[day].items())))
    last = rows[-1]
    lines.append(f"  last: {last['t']}  {last['kind']} {last['outcome']}" + (f" ({last['why']})" if last.get("why") else ""))
    return "\n".join(lines)


class MemoryCallGate:
    """One memory-processing call per session, shared by the consolidator and the reflector."""

    def __init__(self, idle_age=None, *, rearm_below_s: float = 120.0):
        self._idle_age, self._rearm_below_s = idle_age, rearm_below_s
        self._spent_by: str | None = None
        self._skip_logged: set = set()                        # one 'skipped' line per pass per spent session, not one per poll
        self._lock = threading.Lock()

    def acquire(self, kind: str) -> bool:
        with self._lock:
            try:
                age = self._idle_age() if self._idle_age else None
            except Exception:  # noqa: BLE001
                age = None
            if age is not None and age < self._rearm_below_s:      # someone talked to G2 since: a new session
                self._spent_by = None
                self._skip_logged.clear()
            if self._spent_by is not None:
                if kind not in self._skip_logged:
                    self._skip_logged.add(kind)
                    log_call(kind, "skipped", why=f"one memory call per session; {self._spent_by} already made it")
                return False
            self._spent_by = kind
            return True
