"""Line G2 up for a basket shot: find the basket, get to the shot distance facing it, never bump it (the basket goal, docs/plan-detail/basket-goal-plan.md).

A pure decision function (`next_action`) plus a loop (`lineup`) that takes a fresh picture before every decision and asks a mover to do one step. Nothing here moves G2 by itself, calls an API or needs the camera: the mover and the look are handed in
(the walking, the pivot and the picture belong to the tools that run it), so the whole logic is tested without hardware.

Decisions (owner, 2026-11-22): stay facing the basket and walk FORWARD or BACKWARD until the camera reads the shot distance (16 inches from the claw tip), instead of turning his back and walking blind; pivot-scan until the basket is in view when it is not; walk closer when it is far
off; never come within 6 inches of the basket (a buffer, backing up before anything else when inside it); after a pick-up he starts again from a fresh look at the basket, not from where he thought it was. If he cannot align he keeps trying, up to MAX_CORRECTIONS steps, then stops for a reset.
Distances are in inches from the claw tip; bearings in degrees, + to the right. The step sizes and the paces are first guesses to measure on G2 (a pivot turns in whole cycles of about 27 degrees; turns under 18 degrees are small arc pulses).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

TARGET_IN = 16.0              # the shot distance
DIST_TOL_IN = 2.5             # provisional: the basket finder's distance is good to about 1 to 3 inches at this range (vision/basket_finder.py); tighten after calibration
BUFFER_IN = 6.0               # never closer than this to the basket (owner: he can get within 6 inches without pushing it)
CLOSE_MARGIN_IN = 2.0         # inside BUFFER_IN + this he backs up before anything else (no turning next to the basket)
FWD_STEP_MAX_IN, BACK_STEP_MAX_IN, FAR_STEP_MAX_IN, FAR_IN = 6.0, 12.0, 12.0, 30.0     # a back-up is ONE move all the way to the shot distance (the mover caps it at 12)
BACK_DRIFT_RATIO = 0.33       # a backward walk drifts to his right by this fraction of its length (nine timed runs 2026-11-23: 1 of 2, 3 of 9, 3 to 5 of 16 inches; docs/rl/real-walk-log.md)
MIN_STEP_IN = 1.5
ALIGN_TOL_DEG = 3.0          # about 0.8 inch sideways at 16 inches, the sideways spread of the lob
PIVOT_MIN_DEG, PIVOT_CYCLE_DEG = 18.0, 27.0
SCAN_STEP_DEG, SCAN_MAX_DEG = 27.0, 360.0
AIM_OFFSET_DEG = 0.0           # + = aim this far to the right of the basket's centre (the goal learns it): the basket is lined up at this far left of straight ahead, so it reads at minus this bearing
MAX_CORRECTIONS = 30


@dataclass
class Action:
    kind: str                 # "scan" | "pivot" | "nudge" | "forward" | "back" | "shoot" | "give_up"
    value: float = 0.0        # degrees (scan, pivot, nudge; + right) or inches (forward, back)
    why: str = ""


@dataclass
class LineupState:
    scanned_deg: float = 0.0
    corrections: int = 0
    log: list = field(default_factory=list)


def _pivot_for(bearing: float) -> float:
    cycles = max(1, round(abs(bearing) / PIVOT_CYCLE_DEG))
    return cycles * PIVOT_CYCLE_DEG * (1 if bearing > 0 else -1)


def back_inches_to_target(d: float, bearing_deg: float) -> float:
    """How far to back up so the claw tip ends TARGET_IN from the basket after the backward walk's sideways drift. Straight back would end `TARGET_IN - d` inches further; the walk also slides him to his right by BACK_DRIFT_RATIO of its length, which puts
    the basket off to the side and lengthens the straight line to it, so the line is solved from the basket's position (d and the bearing, + right) after a back-up of b inches: sqrt((d cos(bearing) + b)^2 + (d sin(bearing) - ratio b)^2) = TARGET_IN."""
    th = math.radians(bearing_deg)
    ahead, right = d * math.cos(th), d * math.sin(th)

    def dist(b: float) -> float:
        return math.hypot(ahead + b, right - BACK_DRIFT_RATIO * b)

    lo, hi = 0.0, BACK_STEP_MAX_IN
    if dist(hi) <= TARGET_IN:
        return hi
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if dist(mid) < TARGET_IN else (lo, mid)
    return max(MIN_STEP_IN, min(BACK_STEP_MAX_IN, (lo + hi) / 2))


def next_action(reading, st: LineupState) -> Action:
    """The next step from a fresh reading (a BasketReading-like object with `claw_in` and `bearing_deg`, or None when the basket is not in the picture)."""
    if reading is None:
        if st.scanned_deg >= SCAN_MAX_DEG:
            return Action("give_up", 0.0, "basket_not_found")
        st.scanned_deg += SCAN_STEP_DEG
        return Action("scan", SCAN_STEP_DEG, "basket not in view: pivot scan")
    st.scanned_deg = 0.0
    d, b = float(reading.claw_in), float(reading.bearing_deg) + AIM_OFFSET_DEG          # b: the bearing error, how far he is from facing the aim point
    if st.corrections >= MAX_CORRECTIONS:
        return Action("give_up", 0.0, "could_not_align")
    if d < BUFFER_IN + CLOSE_MARGIN_IN:
        st.corrections += 1
        return Action("back", back_inches_to_target(d, b), "inside the buffer: back up first")
    if abs(b) >= PIVOT_MIN_DEG:
        st.corrections += 1
        return Action("pivot", _pivot_for(b), "basket far off to the side: pivot toward it")
    if d - TARGET_IN > DIST_TOL_IN:
        cap = FAR_STEP_MAX_IN if d > FAR_IN else FWD_STEP_MAX_IN
        step = min(cap, d - TARGET_IN, d - BUFFER_IN - CLOSE_MARGIN_IN)                   # never ends inside the buffer
        if step >= MIN_STEP_IN:
            st.corrections += 1
            return Action("forward", step, "too far: walk closer")
    if TARGET_IN - d > DIST_TOL_IN:
        st.corrections += 1
        return Action("back", back_inches_to_target(d, b), "too close: back up")
    if abs(b) > ALIGN_TOL_DEG:
        st.corrections += 1
        return Action("nudge", b, "small alignment turn")
    return Action("shoot", 0.0, "aligned at the shot distance")


def lineup(look, mover, max_steps: int = 60, say=print) -> dict:
    """Run the line-up. `look()` takes a fresh picture and returns a reading or None; `mover` has scan(deg), pivot(deg), nudge(deg), forward(inches), back(inches) (each one step, then still, and answering "fell" when he went over). Returns
    {"outcome": "aligned" | "basket_not_found" | "could_not_align" | "too_many_steps" | "fell", "steps": [...], "last": reading}."""
    st, reading = LineupState(), None
    for _ in range(max_steps):
        reading = look()
        act = next_action(reading, st)
        st.log.append({"action": act.kind, "value": round(act.value, 1), "why": act.why, "claw_in": None if reading is None else round(reading.claw_in, 1),
                       "bearing_deg": None if reading is None else round(reading.bearing_deg, 1)})
        say(f"line-up: {act.why}" + (f" ({act.kind} {act.value:.1f})" if act.kind not in ("shoot", "give_up") else ""))
        if act.kind == "shoot":
            return {"outcome": "aligned", "steps": st.log, "last": reading}
        if act.kind == "give_up":
            return {"outcome": act.why, "steps": st.log, "last": reading}
        if hasattr(mover, "set_distance"):
            mover.set_distance(None if reading is None else float(reading.claw_in))      # the turn picks the in-place pivot or the walking arc by how far the target is (opencat.lineup_tokens), as the ball goal's run loop tells it
        if getattr(mover, act.kind)(act.value) == "fell":                                  # a mover answers "fell" when he went over: the line-up ends there, the caller lays him down
            return {"outcome": "fell", "steps": st.log, "last": reading}
    return {"outcome": "too_many_steps", "steps": st.log, "last": reading}
