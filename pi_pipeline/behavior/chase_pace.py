"""G2 measures his own walking pace and turn rate from the camera (goals plan, 2026-10-31): a measurement, not a judged setting, so it improves with every move.

Every walk toward the ball has a reading before and after it: the distance it closed over the walk's seconds is his pace. Every turn has the ball's bearing before and after: the
angle it swung over the turn's seconds is his turn rate, kept per side (left and right differ on G2) and for short alignment pulses apart from longer turns (a short pulse spends
more of its time getting going). A move is only counted when both readings are clean: the ball whole in the picture, near straight ahead for a walk, and it moved the right way
(a pushed ball, a lost ball or a misread is left out). Kept per attachment, floor and hardware epoch in `~/.local/share/g2/chase_pace.json` (a new one starts from the nearest measured values) (G2_CHASE_PACE moves it), as a running average.

The chase (behavior/ball_chase.py) times each walk and turn with these numbers; until a value has MIN_SAMPLES behind it the defaults below are used.
"""
from __future__ import annotations

import json
import os

PATH = "~/.local/share/g2/chase_pace.json"
ALPHA = 0.3                    # weight of a new sample in the running average
MIN_SAMPLES = 2                # samples before a measured value replaces the default
WALK_START_S = 1.0             # the policy walk covers nothing in about its first second (settle, ramp): not measured, the pace is fitted around it
WALL_PACE_START_S = WALK_START_S
SHORT_TURN_S = 1.6             # a turn this short or shorter is an alignment pulse

DEFAULTS = {"walk_in_s": 4.2,                     # the policy walk with the arm: ARM1R 4 ft 5 in in 12.5 s on hardwood (2026-10-25)
            "turn_deg_s": 28.0,                   # Petoi's firmware turn (kwkL / kwkR, the default gait since 11-03): about 28 deg/s measured; the old 6.0 was the arm-build policy turn (2026-10-25) and made every plain turn overshoot about four times
            "pulse_deg_s": 24.0}                  # a short pulse turns a little less per second than a long turn (line-up pulses also stop on the gyro)
LIMITS = {"walk_in_s": (0.5, 15.0), "turn_deg_s": (0.5, 40.0), "pulse_deg_s": (0.3, 40.0)}


def path() -> str:
    return os.path.expanduser(os.environ.get("G2_CHASE_PACE", PATH))


class PaceBook:
    def __init__(self, key: str = "unknown", p: str | None = None, save: bool = True, fallback: list[str] | None = None):
        self.key, self.path, self._save = key, p or path(), save
        try:
            self._all = json.load(open(self.path))
        except (OSError, ValueError):
            self._all = {}
        if key not in self._all:                     # new conditions (a hardware change, a new floor): start from the nearest measured ones, kept as a starting point only
            for fb in fallback or []:
                if self._all.get(fb):
                    self._all[key] = {n: {"value": e["value"], "n": min(e.get("n", 0), MIN_SAMPLES), "from": fb} for n, e in self._all[fb].items()}
                    break
        self.data = self._all.setdefault(key, {})
        self.log: list = []                          # this run's samples, for the attempt record

    # ------------------------------------------------------------------------------------------------ reading
    def _get(self, name: str) -> float:
        e = self.data.get(name)
        return float(e["value"]) if e and e.get("n", 0) >= MIN_SAMPLES else DEFAULTS[name.split(":")[0]]

    def walk_in_s(self) -> float:
        return self._get("walk_in_s")

    def turn_deg_s(self, side: int, short: bool) -> float:
        base = "pulse_deg_s" if short else "turn_deg_s"
        name = f"{base}:{'right' if side > 0 else 'left'}"
        e = self.data.get(name)
        return float(e["value"]) if e and e.get("n", 0) >= MIN_SAMPLES else DEFAULTS[base]

    def snapshot(self) -> dict:
        return {k: dict(v) for k, v in self.data.items()}

    # ------------------------------------------------------------------------------------------------ measuring
    def _add(self, name: str, value: float) -> float:
        lo, hi = LIMITS[name.split(":")[0]]
        value = max(lo, min(hi, value))
        e = self.data.setdefault(name, {"value": value, "n": 0})
        e["value"] = round(value if e["n"] == 0 else (1 - ALPHA) * e["value"] + ALPHA * value, 3)
        e["n"] += 1
        self.log.append({"what": name, "sample": round(value, 2), "now": e["value"], "n": e["n"]})
        self._write()
        return e["value"]

    def record_walk(self, before, after, seconds: float) -> float | None:
        """`before` / `after`: BallReadings around one walk of `seconds`. Returns the new pace, or None when the pair was not clean."""
        if before is None or after is None or before.touches_edge or after.touches_edge:
            return None
        if abs(before.bearing_deg) > 15 or abs(after.bearing_deg) > 20:
            return None
        closed = before.distance_in - after.distance_in
        moving = seconds - WALK_START_S
        if closed < 0.5 or moving < 0.3:
            return None                              # no progress (pushed, or too short to say) is not a pace
        return self._add("walk_in_s", closed / moving)

    def record_turn(self, before, after, degrees: float, seconds: float) -> float | None:
        """A turn of `seconds` toward `degrees` (+ = right). Turning right moves the ball LEFT in the picture (its bearing drops)."""
        if before is None or after is None or before.touches_edge or after.touches_edge or seconds <= 0 or degrees == 0:
            return None
        side = 1 if degrees > 0 else -1
        swung = (before.bearing_deg - after.bearing_deg) * side
        if swung < 0.5 or swung > 80:
            return None
        base = "pulse_deg_s" if seconds <= SHORT_TURN_S else "turn_deg_s"
        return self._add(f"{base}:{'right' if side > 0 else 'left'}", swung / seconds)

    def _write(self) -> None:
        if not self._save:
            return
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                f.write(json.dumps(self._all, indent=1) + "\n")
            os.replace(tmp, self.path)
        except OSError:
            pass


def book_for_now(save: bool = True) -> PaceBook:
    """The pace book for the fitted attachment and the floor label set now."""
    try:
        from ..attachments import current
        att = current()
    except Exception:  # noqa: BLE001
        att = "unknown"
    try:
        from ..telemetry.autolog import get_surface
        floor = get_surface()
    except Exception:  # noqa: BLE001
        floor = "unknown"
    try:
        from ..telemetry.epochs import epoch_at, load_epochs
        e = epoch_at()
        hw = e["id"] if e else "unknown"
        earlier = [x["id"] for x in reversed(load_epochs()) if x["id"] != hw]
    except Exception:  # noqa: BLE001
        hw, earlier = "unknown", []
    key = f"attachment={att}|floor={floor}|hw={hw}"
    fallback = [f"attachment={att}|floor={floor}|hw={h}" for h in earlier] + [f"attachment={att}|floor={floor}"]     # the older key had no hardware part
    return PaceBook(key, save=save, fallback=fallback)
