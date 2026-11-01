"""The "turn away from walls" standing goal (user, 2026-10-31: always on, ranked above the punt, dialled in by every attempt that meets a wall, in both directions).

An attempt is one wall encounter, in any activity. Exploration (the driver's wall reflex, its hit sequence, the IMU contact signal):

  turned_away      turned away and no touch in the next ENCOUNTER_S                         success
  turned_early     turned away while the wall was still more than EARLY_IN away            success, but votes for turning later (too careful)
  turned_but_hit   turned away and still touched it within ENCOUNTER_S                      failure -> turn sooner and farther
  bumped           touched a wall with no turn away before it                               failure -> turn sooner, look sooner, stop walks shorter

The ball chase (its wall check, and the policy walk's IMU contact signal):

  chase_turned_away      turned away at chase_wall_in, no touch                             success
  chase_left_ball        left a ball lying nearer the wall than chase_wall_in allows        a miss that votes for going closer (too careful)
  chase_turned_but_hit   turned away and still touched it                                   failure -> keep farther
  chase_bumped           walked into something with no turn away                            failure -> keep farther

Each knob is judged by the part it acts in (`STAGE_OF`): the exploration distances by exploration encounters, `chase_wall_in` by chase encounters, the turn by both. Bumps push
the distances out, the "too careful" outcomes pull them in, so they settle where he turns in time without wasting room. `chase_wall_in` never goes below 4 in.

The wall reading is used as it is, calibrated or not: he learns the distances in the reading's own inches, so a consistent error cancels out. A new calibration is a new condition
(its time is part of the conditions key): his records start fresh and his settings start from the old ones carried through both calibrations to the same picture rows
(`translate_prior`), so he turns at the same real distance and re-tunes from there.
"""
from __future__ import annotations

import json
import re

from .approach import AttemptResult, Outcome, register
from .spec import Knob

ENCOUNTER_S = 8.0              # a touch this soon after a turn away belongs to that encounter
SAME_BUMP_S = 3.0              # a hit sequence and an IMU contact this close together are one bump
EARLY_IN = 12.0                # exploring: a turn away with the wall still farther than this (in the reading's inches) was more careful than needed

KNOB_INFO = {                  # name -> (step, control, label, unit)
    "wall_turn_in": (2.0, "free", "turning away from walls at", "in"),
    "wall_stop_in": (2.0, "free", "acting on a single look at a wall from", "in"),
    "wall_turn_deg": (10.0, "free", "turning away from walls by", "deg"),
    "leg_margin_in": (2.0, "free", "stopping my walks", "in from a wall"),
    "near_look_in": (3.0, "free", "looking fast once a wall is within", "in"),
    "chase_wall_in": (1.0, "free", "keeping", "in from walls while chasing"),
}
DISTANCE_KNOBS = ("wall_turn_in", "wall_stop_in", "leg_margin_in", "near_look_in", "chase_wall_in")
STAGE_OF = {"wall_turn_in": "explore", "wall_stop_in": "explore", "leg_margin_in": "explore", "near_look_in": "explore", "chase_wall_in": "chase"}      # wall_turn_deg: both

DIAGNOSIS = {
    "turned_early": [("wall_turn_in", -1)],
    "turned_but_hit": [("wall_turn_in", +1), ("wall_turn_deg", +1), ("wall_stop_in", +1)],
    "bumped": [("wall_turn_in", +1), ("near_look_in", +1), ("wall_stop_in", +1), ("leg_margin_in", +1)],
    "chase_left_ball": [("chase_wall_in", -1)],
    "chase_turned_but_hit": [("chase_wall_in", +1), ("wall_turn_deg", +1)],
    "chase_bumped": [("chase_wall_in", +1)],
}

_NEAR = re.compile(r"\((\d+(?:\.\d+)?) in")


def events_from_trace(trace: list) -> list[dict]:
    """The ball chase's wall events (behavior/ball_chase.py `note(kind="wall")`) as encounter events."""
    out = []
    for e in trace or []:
        if e.get("kind") != "wall":
            continue
        kind = {"steer": "steer", "bump": "hit", "ball_by_wall": "left_ball"}.get(e.get("event"))
        if kind:
            out.append({"t": float(e.get("t", 0.0)), "kind": kind, "nearest_in": e.get("wall_in"), "source": "chase"})
    return out


def events_from_diag(rows: list) -> list[dict]:
    """The exploration's diagnostic events [(t, name, reason)] (reflection/recap.SessionTally.events) as encounter events."""
    out = []
    for t, name, reason in rows or []:
        if name == "wall.steer":
            m = _NEAR.search(str(reason))
            out.append({"t": float(t), "kind": "steer", "nearest_in": float(m.group(1)) if m else None, "source": "explore"})
        elif name in ("wall.hit", "contact"):
            out.append({"t": float(t), "kind": "hit", "source": "explore"})
    return out


def _o(code: str, score: float, success: bool, text: str, source: str, nums: dict) -> Outcome:
    return Outcome(code, score, success, text, nums, stages={"explore" if source == "explore" else "chase": score})


def score_encounters(events: list[dict]) -> list[Outcome]:
    out = []
    for source in ("explore", "chase"):
        evs = sorted((e for e in events if e.get("source", "explore") == source), key=lambda e: e["t"])
        pre = "" if source == "explore" else "chase_"
        bumps = []
        for e in evs:                                           # one bump per touch (the hit sequence and the IMU contact fire together)
            if e["kind"] == "hit" and (not bumps or e["t"] - bumps[-1]["t"] > SAME_BUMP_S):
                bumps.append(e)
        steers = [e for e in evs if e["kind"] == "steer"]
        used = set()
        for i, st in enumerate(steers):
            nxt = steers[i + 1]["t"] if i + 1 < len(steers) else float("inf")
            hit = next((j for j, b in enumerate(bumps) if j not in used and st["t"] <= b["t"] <= min(st["t"] + ENCOUNTER_S, nxt)), None)
            near = st.get("nearest_in")
            where = f" at {near:.0f} in" if near is not None else ""
            nums = {"nearest_in": near, "source": source}
            if hit is not None:
                used.add(hit)
                out.append(_o(pre + "turned_but_hit", 0.2, False, f"I turned away from a wall{where} but still touched it", source, nums))
            elif source == "explore" and near is not None and near > EARLY_IN:
                out.append(_o("turned_early", 0.7, False, f"I turned away from a wall{where}: earlier than I needed", source, nums))
            else:
                out.append(_o(pre + "turned_away", 1.0, True, f"I turned away from a wall{where}", source, nums))
        for j, b in enumerate(bumps):
            if j not in used:
                out.append(_o(pre + "bumped", 0.0, False, "I walked into a wall without turning away" + (" while chasing the ball" if pre else ""), source, {"source": source}))
        for e in evs:
            if e["kind"] == "left_ball":
                out.append(_o("chase_left_ball", 0.4, False, "I left a ball lying by a wall: maybe more careful than I needed", source, {"source": source}))
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
    """The calibration was made on the current hardware (after the latest hardware epoch began). Reported, not required: he learns against the reading as it is."""
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
    """The chase's wall check, or None: walls must rank above the punt and a wall calibration must exist (any: he learns against the reading as it is)."""
    from .spec import ranks_above
    if not ranks_above("walls", "ball_punt"):
        return None
    cal, _when = calibration_info()
    if cal is None:
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
    beside = sorted({g for b in skip for g in (b - 1, b + 1) if 0 <= g < GROUPS} - skip)             # the columns right beside the ball: is it lying against a wall?
    near_ball = [cm[g] for g in beside if cm[g] is not None]
    near_ball_in = round(min(near_ball) / IN_TO_CM, 1) if near_ball else None
    if not seen:
        return WallSeen(None, None, near_ball_in)
    half = GROUPS // 2
    left = [c if c is not None else 1e9 for c in cm[:half]]
    right = [c if c is not None else 1e9 for c in cm[half + 1:]]
    side = "left" if min(left) > min(right) else "right" if min(right) > min(left) else ("left" if sum(left) >= sum(right) else "right")
    return WallSeen(round(min(seen) / IN_TO_CM, 1), side, near_ball_in)


def _row_for_cm(points: list, cm: float) -> float | None:
    """The picture row (0..1) at which a calibration reads `cm` (its inverse, by bisection over the calibrated range)."""
    from ..vision.wall_distance import Calibration
    cal = Calibration([tuple(p) for p in points])
    pts = sorted(cal.points)
    if not pts:
        return None
    lo, hi = pts[0][0], pts[-1][0]
    if cm >= cal.distance_cm(lo):
        return lo
    if cm <= cal.distance_cm(hi):
        return hi
    for _ in range(40):                                           # distance falls as the row grows (lower in the picture = closer)
        mid = (lo + hi) / 2
        if cal.distance_cm(mid) > cm:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def translate(values: dict, old_points: list | None, new_points: list | None) -> dict:
    """Carry distance settings from one calibration to another: the same picture row (the same real distance), read in the new calibration's inches."""
    from ..vision.wall_distance import IN_TO_CM, Calibration
    if not old_points or not new_points or sorted(map(tuple, old_points)) == sorted(map(tuple, new_points)):
        return dict(values)
    new = Calibration([tuple(p) for p in new_points])
    out = dict(values)
    for name in DISTANCE_KNOBS:
        if name in values and values[name] is not None:
            row = _row_for_cm(old_points, float(values[name]) * IN_TO_CM)
            if row is not None:
                out[name] = round(new.distance_cm(row) / IN_TO_CM, 1)
    return out


@register("walls")
class Walls:
    name = "walls"
    diagnosis = DIAGNOSIS
    stage_of = STAGE_OF

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

    def condition_note(self) -> dict:
        """Kept in this goal's record for these conditions: the calibration's points, so a later calibration can carry the settings over."""
        cal, _when = calibration_info()
        return {"wallcal_points": [list(p) for p in cal.points] if cal is not None else None}

    def translate_prior(self, values: dict, from_state: dict) -> dict:
        """His best values under other conditions, carried to this calibration (see the module docstring)."""
        cal, _when = calibration_info()
        return translate(values, from_state.get("wallcal_points"), [list(p) for p in cal.points] if cal is not None else None)

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
