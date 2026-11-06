"""Places memory (user, 2026-11-06): what G2 knows about each room, kept as counts with no dates and no times.

    ~/.local/share/g2/places.json     {"kitchen": {"floor": "tile", "sessions": 5, "goal_sessions": 3, "stops": 12, "items": {"dishwasher": 4}, "hazards": {"fall": 2, "bump": 8}, "views": 14}}
    ~/.local/share/g2/current_place   the room G2 was told he is in (one word or two; it lapses after CURRENT_TTL_S so a moved G2 is not tagged with an old room)

A room is named by a person, never invented (docs/planned/place-memory-plan.md): "you're in the kitchen" by voice, `python -m pi_pipeline.memory place kitchen`, or the Room button in g2pics.
While a room is current, explorations and goal sessions add to it: survey stops (and the pictures taken there carry the room name, not a time), the things the detector saw, falls and bumps, the floor
he stands on. Only counts are kept. A question about a room, or a known room's name in what is said, puts a short summary of it into the prompt (`recall_block`). No API call anywhere.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

CURRENT_TTL_S = 6 * 3600
KNOWN_ROOMS = ("kitchen", "living room", "dining room", "bedroom", "bathroom", "hallway", "hall", "office", "den", "garage", "basement", "porch", "laundry room", "entryway", "foyer",
               "playroom", "family room", "study", "nursery", "attic", "closet", "pantry", "sunroom", "deck", "patio", "yard", "lounge", "mudroom", "front room", "back room")


def path() -> Path:
    return Path(os.path.expanduser(os.environ.get("G2_PLACES", "~/.local/share/g2/places.json")))


def current_path() -> Path:
    return Path(os.path.expanduser(os.environ.get("G2_CURRENT_PLACE", "~/.local/share/g2/current_place")))


def norm(name: str) -> str:
    n = re.sub(r"[^a-z ]", "", (name or "").lower()).strip()
    n = re.sub(r"^(?:the|a|an|my|our)\s+", "", n)
    return re.sub(r"\s+", " ", n)


def load() -> dict:
    try:
        d = json.loads(path().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(d: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, p)


def _entry(d: dict, name: str) -> dict:
    e = d.setdefault(name, {})
    e.setdefault("sessions", 0)
    e.setdefault("goal_sessions", 0)
    e.setdefault("stops", 0)
    e.setdefault("views", 0)
    e.setdefault("items", {})
    e.setdefault("hazards", {})
    return e


def set_current(name: str) -> str | None:
    n = norm(name)
    if not n or len(n.split()) > 3:
        return None
    try:
        p = current_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(n + "\n")
        d = load()
        if n not in d:
            _entry(d, n)
            save(d)
    except OSError:
        return None
    return n


def current(now: float | None = None) -> str | None:
    try:
        p = current_path()
        if (now or time.time()) - p.stat().st_mtime > CURRENT_TTL_S:
            return None
        return norm(p.read_text()) or None
    except OSError:
        return None


def clear_current() -> None:
    try:
        current_path().unlink()
    except OSError:
        pass


def known_names() -> set[str]:
    return set(load()) | set(KNOWN_ROOMS)


def record_session(place: str | None, recap: dict) -> None:
    """An exploration's recap added to the room it ran in: stops, the things seen (counted by stops), falls and bumps. Never raises."""
    try:
        n = norm(place or "")
        if not n or not recap:
            return
        d = load()
        e = _entry(d, n)
        e["sessions"] += 1
        e["stops"] += int(recap.get("stops") or 0)
        for label, k in (recap.get("seen") or {}).items():
            e["items"][label] = e["items"].get(label, 0) + int(k)
        ev = recap.get("events") or {}
        for src, key in (("fall", "fall"), ("wall.hit", "bump")):
            if ev.get(src):
                e["hazards"][key] = e["hazards"].get(key, 0) + int(ev[src])
        save(d)
    except Exception:  # noqa: BLE001
        pass


def record_goal(place: str | None, why: str | None = None, floor: str | None = None) -> None:
    """A goal session ran in this room (`why` "fell" counts a fall there); `floor` is the floor label of the session. Never raises."""
    try:
        n = norm(place or "")
        if not n:
            return
        d = load()
        e = _entry(d, n)
        e["goal_sessions"] += 1
        if why == "fell":
            e["hazards"]["fall"] = e["hazards"].get("fall", 0) + 1
        if floor:
            e["floor"] = str(floor)
        save(d)
    except Exception:  # noqa: BLE001
        pass


def note_view(place: str | None) -> None:
    """A picture was taken here (the picture's sidecar carries the room name, not a time)."""
    try:
        n = norm(place or "")
        if n:
            d = load()
            _entry(d, n)["views"] += 1
            save(d)
    except Exception:  # noqa: BLE001
        pass


def import_tagged(stats: dict) -> int:
    """The room tags a person set on pictures in g2pics (kept on the Mac) as per-room counts: {"kitchen": {"views": 36, "items": {"dog bowl": 2, "cat": 1}}}. They replace the previous import of the same
    room (`tagged`), so importing twice never counts a picture twice. Returns how many rooms. Never raises."""
    try:
        d = load()
        n = 0
        for raw, st in (stats or {}).items():
            name = norm(raw)
            if not name or not isinstance(st, dict):
                continue
            e = _entry(d, name)
            e["tagged"] = {"views": int(st.get("views") or 0), "items": {str(k): int(v) for k, v in (st.get("items") or {}).items()}}
            n += 1
        save(d)
        return n
    except Exception:  # noqa: BLE001
        return 0


def _items(e: dict) -> dict:
    out = dict(e.get("items") or {})
    for k, v in ((e.get("tagged") or {}).get("items") or {}).items():
        out[k] = out.get(k, 0) + v
    return out


def summary(name: str, e: dict | None = None) -> str:
    e = e if e is not None else load().get(name) or {}
    bits = []
    if e.get("floor"):
        bits.append(f"{e['floor']} floor")
    items = sorted(_items(e).items(), key=lambda kv: -kv[1])[:4]
    if items:
        bits.append("I often see " + ", ".join(k for k, _ in items))
    hz = e.get("hazards") or {}
    if hz.get("fall"):
        bits.append(f"I have fallen here {hz['fall']} time{'s' if hz['fall'] != 1 else ''}")
    if hz.get("bump"):
        bits.append(f"I have bumped into things here {hz['bump']} times")
    visits = int(e.get("sessions", 0)) + int(e.get("goal_sessions", 0))
    if visits:
        bits.append(f"I have been there {visits} time{'s' if visits != 1 else ''}")
    views = int(e.get("views", 0)) + int((e.get("tagged") or {}).get("views", 0))
    if views:
        bits.append(f"I know it from {views} pictures")
    return f"The {name}: " + "; ".join(bits) + "." if bits else ""


_PLACE_Q = re.compile(r"\b(which room|what room|where am i|where are we|rooms?|around (?:the|this) house|in the house|where (?:do|did|have) you)\b", re.I)


def recall_block(user_text: str, limit: int = 3) -> str:
    """Summaries of the rooms the person mentioned, or of the busiest rooms when they ask about rooms in general. "" when nothing applies."""
    d = load()
    if not d:
        return ""
    t = (user_text or "").lower()
    named = [n for n in d if re.search(r"\b" + re.escape(n) + r"\b", t)]
    cur = current()
    if not named and _PLACE_Q.search(t):
        named = sorted(d, key=lambda n: -(int(d[n].get("sessions", 0)) + int(d[n].get("goal_sessions", 0)) + int(d[n].get("stops", 0))))
        if cur and cur in d:
            named = [cur] + [n for n in named if n != cur]
    lines = [s for s in (summary(n, d[n]) for n in named[:limit]) if s]
    if cur and (named or _PLACE_Q.search(t)):
        lines.insert(0, f"You were last told you are in the {cur}.")
    return "\n".join(lines)
