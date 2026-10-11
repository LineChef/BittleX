"""Level 1 of reflection: a recap of each exploration session, counted from what G2's own code already knows. No picture, no API call.

`SessionTally` counts the behavior layer's diagnostic events (a turn away from a wall, a hit, a survey stop, a fall...). When the session ends, `build_recap` joins those counts with the
place-memory stop records (`behavior/place_log.py`) and the wall-look log, and `ExperienceLog.append` keeps one JSON line per session in `~/.local/share/g2/experiences.jsonl` (on the Pi, never in
the repo). `recap_text` turns one recap into the sentences G2 says when asked what he did. Everything here swallows its own errors: a recap must never disturb a session.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter
from pathlib import Path

log = logging.getLogger("g2.recap")

DEFAULT_PATH = "~/.local/share/g2/experiences.jsonl"

# the diagnostic events worth counting, and what the recap calls them
COUNTED = ("wall.steer", "wall.hit", "survey.start", "naming.start", "cliff.reflex", "fall", "contact")


def experiences_path() -> str:
    return os.path.expanduser(os.environ.get("G2_EXPERIENCES", DEFAULT_PATH))


class SessionTally:
    """Counts events by name; `note(name)` is safe to call from any thread."""

    def __init__(self):
        self._c: Counter = Counter()
        self._lock = threading.Lock()

    def note(self, name, reason: str = "") -> None:
        try:
            name = str(name)
            if name in COUNTED:
                with self._lock:
                    self._c[name] += 1
        except Exception:  # noqa: BLE001
            pass

    def counts(self) -> dict:
        with self._lock:
            return dict(self._c)

    def wrap(self, on_diag):
        """A drop-in `on_diag(name, reason)` that counts, then calls the original."""
        def _both(name, reason=""):
            self.note(name, reason)
            if on_diag is not None:
                on_diag(name, reason)
        return _both


def _wall_window(path: str, t0: float, t1: float) -> dict:
    """What the wall estimator saw between two times: looks, how many were near / blocked, the closest wall base (inches)."""
    looks = Counter()
    closest = None
    try:
        for line in Path(os.path.expanduser(path)).read_text().splitlines():
            try:
                d = json.loads(line)
                t = time.mktime(time.strptime(d["t"], "%Y-%m-%d %H:%M:%S"))
            except (ValueError, KeyError):
                continue
            if not t0 <= t <= t1 or not d.get("calibrated", True) or d.get("state") is None:
                continue
            looks[d["state"]] += 1
            n = d.get("nearest_in")
            if n is not None and (closest is None or n < closest):
                closest = n
    except OSError:
        pass
    return {"looks": sum(looks.values()), "near": looks.get("near", 0) + looks.get("blocked", 0), "closest_in": closest}


def build_recap(tally: SessionTally | None, *, started: float, ended: float, ended_by: str = "", stops: list | None = None, wall_path: str | None = None) -> dict:
    """One session's recap as a plain dict (see the module docstring). `started` / `ended` are wall-clock times (time.time())."""
    stops = list(stops or [])
    seen: Counter = Counter()
    for s in stops:
        for label in {d.get("label") for d in (s.get("detections") or []) if d.get("label")}:
            seen[label] += 1                                          # at how many stops each thing was in view
    return {"started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)), "duration_s": round(max(0.0, ended - started)), "ended_by": ended_by,
            "events": tally.counts() if tally else {}, "stops": len(stops), "seen": dict(seen),
            "rooms": dict(Counter(s["room"] for s in stops if s.get("room"))),
            "wall": _wall_window(wall_path, started, ended) if wall_path else {"looks": 0, "near": 0, "closest_in": None}}


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def _times(count: int) -> str:
    return "once" if count == 1 else "twice" if count == 2 else f"{count} times"


def recap_text(r: dict) -> str:
    """The sentences G2 says about one session, in plain words."""
    if not r:
        return "I haven't been exploring yet, so I have nothing to tell."
    ev = r.get("events") or {}
    mins = round((r.get("duration_s") or 0) / 60)
    parts = [("I explored for about " + _n(mins, "minute") + ".") if mins >= 1 else "I explored for less than a minute."]
    if r.get("stops"):
        parts.append(f"I stopped {_times(r['stops'])} to look around.")
    seen = sorted((r.get("seen") or {}).items(), key=lambda kv: -kv[1])[:3]
    if seen:
        parts.append("I saw " + ", ".join(f"a {k}" + (f" at {_n(v, 'stop')}" if v > 1 else "") for k, v in seen) + ".")
    rooms = sorted((r.get("rooms") or {}).items(), key=lambda kv: -kv[1])
    if rooms:
        parts.append("I was mostly in the " + rooms[0][0] + ".")
    steer, hit = ev.get("wall.steer", 0), ev.get("wall.hit", 0)
    if steer:
        parts.append(f"I turned away from a wall {_times(steer)}.")
    if hit:
        parts.append(f"I bumped into something {_times(hit)}.")
    closest = (r.get("wall") or {}).get("closest_in")
    if closest is not None and closest < 12:
        parts.append(f"The closest I got to a wall was about {round(closest)} inches.")
    if ev.get("fall"):
        parts.append(f"I fell down {_times(ev['fall'])}.")
    if not (steer or hit or ev.get("fall")):
        parts.append("Nothing went wrong.")
    return " ".join(parts)


class ExperienceLog:
    def __init__(self, path: str | None = None):
        self.path = Path(path or experiences_path()).expanduser()

    def read(self) -> list[dict]:
        out = []
        try:
            for line in self.path.read_text().splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            pass
        return out

    def append(self, recap: dict) -> dict | None:
        """Number the recap (1, 2, ...) and add it; returns the stored record or None when it could not be written."""
        try:
            rec = {"id": len(self.read()) + 1, **recap}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            return rec
        except Exception:  # noqa: BLE001
            log.exception("could not keep the session recap")
            return None

    def latest(self) -> dict | None:
        rows = self.read()
        return rows[-1] if rows else None

    def after(self, last_id: int) -> list[dict]:
        return [r for r in self.read() if int(r.get("id", 0)) > last_id]
