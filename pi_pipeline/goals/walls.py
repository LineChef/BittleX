"""The "turn away from walls" standing goal (user, 2026-10-31: always on, ranked above the punt).

An attempt is one wall encounter, in any activity: exploration (the driver's wall reflex and hit sequence, the IMU contact signal) and the ball chase (its wall check). Scored:

  turned_away      he turned away from a wall and did not touch it in the next ENCOUNTER_S          success
  turned_but_hit   he turned away but touched it within ENCOUNTER_S (too late or too little)        failure -> stop farther out, turn farther
  bumped           he touched a wall with no turn away before it (he never saw it coming)          failure -> look sooner, stop farther out, cut walks shorter

His knobs are the wall settings (`behavior/wall_settings.py`). `chase_wall_in` (how close the chase may get to a wall) is fixed: only the user moves it. Nothing pushes the others
back toward a wall, so this goal only makes him more careful; a value that does no better is still left behind by the judge's record.

The wall check in the chase uses the camera's wall reading only when its calibration was made on the current hardware (a calibration older than the latest hardware epoch is
ignored), and only while walls rank above the punt. The calibration's time is part of this goal's conditions: a new calibration starts fresh records, like a hardware change.
"""
from __future__ import annotations

import json
import re

from .approach import AttemptResult, Outcome, register
from .spec import Knob

ENCOUNTER_S = 8.0              # a touch this soon after a turn away belongs to that encounter
SAME_BUMP_S = 3.0              # a hit sequence and an IMU contact this close together are one bump

KNOB_INFO = {                  # name -> (step, control, label, unit)
    "wall_stop_in": (2.0, "free", "acting on a single look at a wall from", "in"),
    "wall_turn_deg": (10.0, "free", "turning away from walls by", "deg"),
    "leg_margin_in": (2.0, "free", "stopping my walks", "in from a wall"),
    "near_look_in": (3.0, "free", "looking fast once a wall is within", "in"),
    "chase_wall_in": (1.0, "fixed", "keeping at least", "in from walls while chasing"),
}

DIAGNOSIS = {
    "turned_but_hit": [("wall_stop_in", +1), ("wall_turn_deg", +1)],
    "bumped": [("near_look_in", +1), ("wall_stop_in", +1), ("leg_margin_in", +1)],
}

_NEAR = re.compile(r"\((\d+(?:\.\d+)?) in")


def events_from_trace(trace: list) -> list[dict]:
    """The ball chase's wall events (behavior/ball_chase.py `note(kind="wall")`) as encounter events."""
    out = []
    for e in trace or []:
        if e.get("kind") == "wall" and e.get("event") == "steer":
            out.append({"t": float(e.get("t", 0.0)), "kind": "steer", "nearest_in": e.get("wall_in")})
    return out


def events_from_diag(rows: list) -> list[dict]:
    """The exploration's diagnostic events [(t, name, reason)] (reflection/recap.SessionTally.events) as encounter events."""
    out = []
    for t, name, reason in rows or []:
        if name == "wall.steer":
            m = _NEAR.search(str(reason))
            out.append({"t": float(t), "kind": "steer", "nearest_in": float(m.group(1)) if m else None})
        elif name in ("wall.hit", "contact"):
            out.append({"t": float(t), "kind": "hit"})
    return out


def score_encounters(events: list[dict]) -> list[Outcome]:
    evs = sorted(events, key=lambda e: e["t"])
    bumps = []
    for e in evs:                                               # one bump per touch (the hit sequence and the IMU contact fire together)
        if e["kind"] == "hit" and (not bumps or e["t"] - bumps[-1]["t"] > SAME_BUMP_S):
            bumps.append(e)
    steers = [e for e in evs if e["kind"] == "steer"]
    out = []
    used_bumps = set()
    for i, st in enumerate(steers):
        nxt = steers[i + 1]["t"] if i + 1 < len(steers) else float("inf")
        hit = next((j for j, b in enumerate(bumps) if j not in used_bumps and st["t"] <= b["t"] <= min(st["t"] + ENCOUNTER_S, nxt)), None)
        near = st.get("nearest_in")
        where = f" at {near:.0f} in" if near is not None else ""
        if hit is None:
            out.append(Outcome("turned_away", 1.0, True, f"I turned away from a wall{where}", {"nearest_in": near}))
        else:
            used_bumps.add(hit)
            out.append(Outcome("turned_but_hit", 0.2, False, f"I turned away from a wall{where} but still touched it", {"nearest_in": near}))
    for j, b in enumerate(bumps):
        if j not in used_bumps:
            out.append(Outcome("bumped", 0.0, False, "I walked into a wall without turning away", {}))
    return out


def calibration_info() -> tuple[object, str | None]:
    """(the wall calibration, its time) or (None, None)."""
    try:
        from ..vision.wall_distance import CAL_PATH, Calibration
        cal = Calibration.load(CAL_PATH)
        when = json.load(open(CAL_PATH)).get("time") if cal is not None else None
        return cal, when
    except Exception:  # noqa: BLE001
        return None, None


def calibration_current(when: str | None) -> bool:
    """The calibration was made on the current hardware (after the latest hardware epoch began)."""
    if not when:
        return False
    try:
        from datetime import datetime

        from ..telemetry.epochs import epoch_at
        e = epoch_at()
        if not e:
            return True
        return datetime.strptime(when, "%Y-%m-%d %H:%M:%S") >= datetime.fromisoformat(e["start"])
    except Exception:  # noqa: BLE001
        return False


def make_wall_check():
    """The chase's wall check, or None: walls must rank above the punt and the calibration must be from the current hardware."""
    from .spec import ranks_above
    if not ranks_above("walls", "ball_punt"):
        return None
    cal, when = calibration_info()
    if cal is None or not calibration_current(when):
        return None
    return lambda jpeg, ball: wall_seen(jpeg, ball, cal)


def wall_seen(jpeg: bytes, ball, cal):
    """The nearest wall base ahead (inches) with the ball's own columns left out, and the side with more room."""
    from ..behavior.ball_chase import WallSeen
    from ..vision.embedder import to_image
    from ..vision.wall_distance import GROUPS, IN_TO_CM, estimate
    if not jpeg:
        return None
    est = estimate(to_image(jpeg), cal)
    if est.blocked:
        return WallSeen(0.0, est.turn or "left")
    width = 240.0
    skip = set()
    if ball is not None:                                          # the ball sits on the floor too: its base must not read as a wall
        lo, hi = ball.x - ball.width / 2 - 4, ball.x + ball.width / 2 + 4
        for g in range(GROUPS):
            g0, g1 = g * width / GROUPS, (g + 1) * width / GROUPS
            if g1 >= lo and g0 <= hi:
                skip.add(g)
    cm = [None if (i in skip) else c for i, c in enumerate(est.group_cm)]
    seen = [c for c in cm if c is not None]
    if not seen:
        return WallSeen(None, None)
    half = GROUPS // 2
    left = [c if c is not None else 1e9 for c in cm[:half]]
    right = [c if c is not None else 1e9 for c in cm[half + 1:]]
    side = "left" if min(left) > min(right) else "right" if min(right) > min(left) else ("left" if sum(left) >= sum(right) else "right")
    return WallSeen(round(min(seen) / IN_TO_CM, 1), side)


@register("walls")
class Walls:
    name = "walls"
    diagnosis = DIAGNOSIS
    stage_of: dict = {}

    def knobs(self) -> list[Knob]:
        from ..behavior import wall_settings as ws
        out = []
        for name, (_where, _const, _kind, lo, hi, _doc) in ws.SPEC.items():
            step, control, label, unit = KNOB_INFO.get(name, (None, "fixed", "", ""))
            out.append(Knob(name, "float", lo=lo, hi=hi, step=step, control=control, label=label, unit=unit))
        return out

    def base_settings(self) -> dict:
        from ..behavior import wall_settings as ws
        eff, _problems = ws.effective()
        return eff

    def conditions(self) -> dict:
        _cal, when = calibration_info()
        return {"wallcal": (when or "none").replace(" ", "T")}

    def apply(self, settings: dict) -> None:
        from ..behavior import wall_settings as ws
        ws.apply(settings)

    # a standing goal has no attempts of its own: its encounters come from other activities (goals/standing.py)
    def run_attempt(self, settings, ctx) -> AttemptResult:
        raise NotImplementedError("walls is a standing goal: practise it with an exploration roam")

    def score(self, result, settings) -> Outcome:
        raise NotImplementedError

    def battery_ok(self, min_pct: int):
        return True, ""

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass
