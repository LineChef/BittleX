"""The full basket sequence, as one process on one serial connection (the basket goal, docs/plan-detail/basket-goal-plan.md, steps 3 to 5; owner, 2026-11-23).

THE STEPS, every attempt: stand up, pick up, throw with nothing in between (the lob: `behavior/lob.py` through `scripted_skill.play`, played to its end), then THE BALL GOAL'S OWN CLAW LOOK, complete (`claw_survey.run_claw_look`: the attention pose, the claw up in two steps, a settle, the pictures, the claw down, the eased stand-up), read by the basket and puck finders
(`goals/basket_outcome.classify_throw`). The basket is a clear tub with red tape on its rim (owner, 2026-11-24). From about 16 inches a puck inside it is 0 to 5 coloured pixels, so that look can see a puck on the floor (a miss, the retrieval starts at once) but not inside. The puck NOT seen: the CONFIRM LOOK (`confirm_throw`): he walks up to about 8 inches of the tub (the line-up's steps and 6 inch buffer),
takes one picture there (the walk-up's own last quick picture, claw down, read at once so he never stands idle; `CONFIRM_LOOK = "claw_up"` goes into the attention pose and takes one centred picture with `claw_survey.run_claw_look(..., centre_only=True)` instead), read for a puck inside the tub. A puck inside is a make: he lies down and the run ends for the owner's reset. Nothing inside is a miss and he CIRCLES the tub (`circle_search`: a wide 45 degree arc at a time with the tub beside him, a peek toward it between arcs, up to two laps, pivoting toward it when it drops out of view) until the puck is seen, then fetches it as after any miss;
two laps without it end the run at rest. Every look picture and what the finders read on it is kept on the Pi (`save_picture`: `~/g2_runs/basket_run/pictures/<run>/`, with `pictures.jsonl`).
A miss: he searches for the puck (pivot scan, quick claw-down pictures), walks to it (the line-up's movers, the pace book's paces), walks the last inches and picks it up with `pickF`, checks by a picture that it is gone from the floor, lines up on the basket again (`basket_lineup.lineup`: quick pictures with the claw down) and throws the next attempt without a pick-up.
Stops: 5 attempts, a fall, no picture after the throw, a basket never found, a puck never found or reached, three failed pick-ups, and never closer than the line-up's buffer to the basket. The camera is warmed up with two silent pictures at the start, before anything moves. Every stage is logged to `~/g2_runs/basket_run/` as it happens.
Everything I had rebuilt in place of that look (raw `kcalib`, `gb` writes, a fast claw, a legs-holding lowering frame, a lie-down before the stand-up) was followed by the board's own `up` and a flip in 10 runs; see the real walk log, "The board's own stand-up after the claw lowers".
A miss: he searches for the puck (pivot scan, quick claw-down pictures), walks to it (the line-up's movers, the pace book's paces), walks the last inches and picks it up with `pickF`, checks by a picture that it is gone from the floor, lines up on the basket again (`basket_lineup.lineup`: quick pictures with the claw down) and throws the next attempt without a pick-up.
Stops: 5 attempts, a fall, no picture after the throw, a basket never found, a puck never found or reached, three failed pick-ups, and never closer than the line-up's buffer to the basket. The camera is warmed up with two silent pictures at the start, before anything moves. Every stage is logged to `~/g2_runs/basket_run/` as it happens.

`next_retrieval_action` and `run_sequence` are pure (the robot, the camera and the throw are handed in as an `Env`), tested on a simulated floor; `RealEnv` wires them to G2 and is only used by `main`. UNPROVEN on G2: the first runs are watched by the owner (a separate process, `g2basket`).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from . import basket_lineup as bl
from ..goals import basket_outcome as bo
from ..vision.object_finder import ObjectReading

MAX_ATTEMPTS = 5
MAX_RETRIEVAL_STEPS = 20             # walking steps (pivots, turns, walks, pick-ups); the pivot scans have their own cap
MAX_SCANS = 30                        # about two full circles of scan pivots in all, however often the puck is seen and lost (owner, 2026-11-23: scans must not use up the walking steps)
BLIND_STEP_IN = 1.5                   # a puck at the claw tip (its blob cut off at the bottom of the picture): the finder's distance is wrong, so one short blind step, then the pick-up
PICK_TRIES = 6
SCAN_STEP_DEG, SCAN_MAX_DEG = 27.0, 360.0
ALIGN_DEG = 6.0                      # the puck's bearing must be inside this before the last walk (a pick-up window is about 1 inch wide)
PICK_STAND_IN = 7.0                  # nearer than this and centred, he makes the last walk and picks up
APPROACH_TOL_IN = 1.5
APPROACH_STEP_MAX_IN = 10.0
PICK_UNDERSHOOT_IN = 1.5             # the last walk stops this short of the finder's distance: the puck must be at the claw tip, and a puck pushed away is lost
BASKET_GUARD_IN = bl.BUFFER_IN + bl.CLOSE_MARGIN_IN
EDGE_GUARD_IN, EDGE_GUARD_WIDTH_PX = 12.0, 80    # a basket cut off by the frame's edge counts as right beside him only when it also reads this near (a clipped basket's width is low, so its distance reads long) or is this wide; a far, small, clipped one is just out of frame (2026-11-23: a basket 17 inches out ended a run)
GONE_WITHIN_IN = 12.0                # after a pick-up a puck still seen on the floor this near means the pick-up missed
CONFIRM_LOOK = "quick"               # "quick": the walk-up's own last picture (claw down, taken at once, read at once: no attention-pose cycle, no standing about) is the confirm picture (owner, 2026-11-24: "he can just walk up and take a fast picture, but he can't be standing idle for a long time afterwards"); "claw_up": the attention-pose look as first built (`env.confirm_look()`)
CAMERA_MISSES_MAX = 2                # this many pictures in a row with no answer while he stands in the walk-up: he lies down and the attempt stops (a stalled camera must not leave him standing: the legs sag after about 10 s)
CIRCLE_RADIUS_IN = 13.0              # the circle's radius as the finder reads it: near enough that a puck within about 8 inches of the tub is inside the puck finder's range, far enough from the 6 inch buffer
CIRCLE_MIN_IN = 10.0                 # nearer than this (as read) he backs off before anything else (the first goal run ended a leg 4.5 inches from the tub)
CIRCLE_ARC_DEG = 45.0                # one wide arc's heading change: 8 arcs a lap
CIRCLE_SQUARE_DEG = 90.0             # facing the tub, this pivot puts it beside him (checked by the gyro: the tub is out of the picture at 90 degrees)
CIRCLE_PEEK_DEG = 60.0               # between arcs: turn this far toward the tub, which then stands about 30 degrees off his nose, look, and turn back
CIRCLE_FACE_TOL_DEG = 8.0            # facing the tub: its bearing inside this before the circle starts
CIRCLE_RADIUS_GAIN = 2.0             # degrees of extra turn away from (or toward) the tub per inch the radius is off (clamped)
CIRCLE_CORRECTION_MAX_DEG = 25.0
CIRCLE_LOST_STEP_DEG = 30.0          # the tub out of view: pivot this much toward its side
CIRCLE_TAPE_GUARD_IN = 12.0          # a "puck" in view with the tub out of view, when the tub was last read nearer than this, is the tub's own red tape seen from too close, not a puck (the first goal run chased it for 22 scans)
CIRCLE_MAX_LAPS = 2.0                # more than two laps without the puck ends the session (owner, 2026-11-24)
CIRCLE_MAX_STEPS = 150
LOG_DIR = "~/g2_runs/basket_run"
AFTER_PICTURE_TIMEOUT_S = 8.0          # the camera's wait for one picture during the run (the first picture after a cold start can take about 10 s: nothing is taken earlier, by the owner's rule)


@dataclass
class RAction:
    kind: str                        # "scan" | "pivot" | "nudge" | "forward" | "pick" | "give_up"
    value: float = 0.0               # degrees (scan, pivot, nudge; + right) or inches (forward, pick: the last walk)
    why: str = ""


@dataclass
class RState:
    scanned_deg: float = 0.0
    scan_dir: int = 1                # + right: the pivot scan keeps turning the way the last turn toward the puck went (2026-11-23: a scan to the right undid a turn to the left)
    steps: int = 0
    scans: int = 0
    picks: int = 0
    log: list = field(default_factory=list)


def next_retrieval_action(puck, basket, st: RState) -> RAction:
    """The next step toward the puck from a fresh look (a PuckReading or None, and the basket reading or None in the same picture)."""
    if st.steps >= MAX_RETRIEVAL_STEPS:
        return RAction("give_up", 0.0, "could_not_reach_puck")
    if basket is not None and (basket.claw_in < BASKET_GUARD_IN or (getattr(basket, "touches_edge", False) and (basket.claw_in <= EDGE_GUARD_IN or basket.width_px >= EDGE_GUARD_WIDTH_PX))):
        return RAction("give_up", 0.0, "too_near_the_basket")
    if puck is None:
        if st.scanned_deg >= SCAN_MAX_DEG or st.scans >= MAX_SCANS:
            return RAction("give_up", 0.0, "puck_not_found")
        st.scanned_deg += SCAN_STEP_DEG
        st.scans += 1
        return RAction("scan", SCAN_STEP_DEG * st.scan_dir, "puck not in view: pivot scan")
    st.scanned_deg = 0.0
    d, b = float(puck.claw_in), float(puck.bearing_deg)
    if abs(b) > ALIGN_DEG:
        st.scan_dir = 1 if b > 0 else -1
    if abs(b) >= bl.PIVOT_MIN_DEG:
        st.steps += 1
        return RAction("pivot", bl._pivot_for(b), "puck far off to the side: pivot toward it")
    if abs(b) > ALIGN_DEG:
        st.steps += 1
        return RAction("nudge", b, "small turn onto the puck")
    if getattr(puck, "clipped", False):                                                   # at the claw tip already (owner, 2026-11-23: line up until one step away, one blind step, then the pick-up)
        return RAction("pick", BLIND_STEP_IN, "puck at the claw tip: one blind step, then the pick-up")
    if d > PICK_STAND_IN + APPROACH_TOL_IN:
        st.steps += 1
        return RAction("forward", min(APPROACH_STEP_MAX_IN, d - PICK_STAND_IN), "walk up to the puck")
    return RAction("pick", max(0.0, d - PICK_UNDERSHOOT_IN), "centred and close: the last walk, then the pick-up")


def _box(reading, name: str) -> ObjectReading | None:
    """The finders' readings as the outcome classifier's ObjectReading (it works on the blobs' boxes)."""
    if reading is None:
        return None
    w, h = float(reading.width_px), float(reading.height_px)
    left, top = int(reading.x - w / 2), int(reading.y - h / 2)
    return ObjectReading(name, reading.x, reading.y, left, int(left + w - 1), top, int(top + h - 1), int(getattr(reading, "area", w * h)), int(w), float(reading.claw_in), reading.bearing_deg, bool(getattr(reading, "touches_edge", False)))


def classify_after(basket, puck, tub_puck=None, confirm: bool = False) -> tuple[str, str]:
    """(code, plain words) for one throw from a look afterwards: `goals/basket_outcome.classify_throw`, the one place the rule lives. `puck`: a puck on the floor outside the tub; `tub_puck`: one seen inside it (only the close confirm look can see one); `confirm`: this is the close look, where
    nothing inside is a miss. The after-throw look from about 16 inches cannot see inside the tub (the tub's clear walls show a puck there as 0 to 5 coloured pixels): a puck not seen anywhere is NOT_SEEN, a question for the confirm look (owner, 2026-11-24)."""
    return bo.classify_throw(basket, puck, tub_puck, confirm)


@dataclass
class CircleState:
    angle_deg: float = 0.0           # how far round the tub he has gone, in degrees: the arcs' heading change as the gyro reports it (one lap is 360 whatever the radius, as long as the tub stays on the same side)
    steps: int = 0
    lost_deg: float = 0.0
    side: int = 1                    # the side the tub is kept on: +1 his right (the arcs curve right), -1 his left
    phase: str = "face"              # "face" (find the tub and face it) -> "arc" (a wide turn) -> "peek" (turn toward the tub) -> "look" (read it, correct, turn back) -> "arc" ...
    last_d: float | None = None      # the last tub distance read
    log: list = field(default_factory=list)

    @property
    def needs_look(self) -> bool:
        return self.phase in ("face", "look")


def next_circle_action(puck, basket, st: CircleState) -> RAction:
    """The next step of the circling search (pure, like `next_retrieval_action`). The circle is one wide ARC at a time round the tub kept beside him (owner, 2026-11-24): face the tub, pivot 90 degrees so it is beside him, then arc CIRCLE_ARC_DEG toward it (the firmware's walking arc curves forward while it turns),
    peek (turn CIRCLE_PEEK_DEG toward the tub so it is about 30 degrees off his nose), look (the tub's distance and bearing, and the puck), correct the radius by how far he turns back (away from the tub when he is too near), and arc again. 360 degrees of arcs is one lap. A puck in view ends it ("found");
    CIRCLE_MAX_LAPS laps end it ("circled_twice"); the tub out of view makes him pivot toward its side ("tub_lost" after a full turn); nearer than CIRCLE_MIN_IN he backs off first."""
    import math
    if st.phase == "arc":
        st.phase = "peek"
        st.steps += 1
        return RAction("arc", st.side * CIRCLE_ARC_DEG, "circling: wide arc round the tub")
    if st.phase == "peek":
        st.phase = "look"
        return RAction("pivot", bl._pivot_for(st.side * CIRCLE_PEEK_DEG), "circling: turn toward the tub to look")
    if puck is not None:
        return RAction("found", 0.0, "puck in view")
    if st.steps >= CIRCLE_MAX_STEPS or st.angle_deg >= 360.0 * CIRCLE_MAX_LAPS:
        return RAction("give_up", 0.0, "circled_twice")
    if basket is None:
        if st.lost_deg >= 360.0:
            return RAction("give_up", 0.0, "tub_lost")
        st.lost_deg += CIRCLE_LOST_STEP_DEG
        st.steps += 1
        return RAction("pivot", st.side * CIRCLE_LOST_STEP_DEG, "tub out of view: pivot toward the side it should be on")
    st.lost_deg = 0.0
    d, b = float(basket.claw_in), float(basket.bearing_deg)
    st.last_d = d
    if d < CIRCLE_MIN_IN:
        st.steps += 1
        return RAction("back", min(bl.BACK_STEP_MAX_IN, CIRCLE_RADIUS_IN - d), "circling: too near the tub, back off")
    if st.phase == "face":
        if abs(b) > CIRCLE_FACE_TOL_DEG:
            st.steps += 1
            return RAction("pivot" if abs(b) >= bl.PIVOT_MIN_DEG else "nudge", bl._pivot_for(b) if abs(b) >= bl.PIVOT_MIN_DEG else b, "circling: face the tub")
        st.phase = "arc"
        st.steps += 1
        return RAction("pivot", bl._pivot_for(-st.side * CIRCLE_SQUARE_DEG), "circling: turn so the tub is beside him")
    # phase "look": he has turned toward the tub; turn back so the tub ends up beside him, a little more away from it when he is too near and less when too far
    correction = max(-CIRCLE_CORRECTION_MAX_DEG, min(CIRCLE_CORRECTION_MAX_DEG, CIRCLE_RADIUS_GAIN * (CIRCLE_RADIUS_IN - d)))
    turn_back = CIRCLE_SQUARE_DEG + correction - abs(b)
    st.phase = "arc"
    st.steps += 1
    return RAction("pivot" if abs(turn_back) >= bl.PIVOT_MIN_DEG else "nudge", -st.side * (bl._pivot_for(turn_back) if abs(turn_back) >= bl.PIVOT_MIN_DEG else turn_back), "circling: turn back so the tub is beside him")


def circle_search(env, say=print, on_step=None, start_side: int = 1) -> dict:
    """Search round the tub for the puck. Returns {"outcome": "found" | "circled_twice" | "tub_lost" | "fell", "puck", "basket", "steps"}; `puck` and `basket` are the last readings when it is found. Uses the environment's quick look and the movers: pivots, a wide `arc`, a back-off."""
    st = CircleState(side=start_side)
    basket = puck = None
    while True:
        if st.needs_look:
            try:
                basket, puck = env.look()
            except Fell:
                return {"outcome": "fell", "puck": None, "basket": None, "steps": st.log}
            if basket is not None:
                st.last_d = float(basket.claw_in)
            elif puck is not None and st.last_d is not None and st.last_d < CIRCLE_TAPE_GUARD_IN:
                say("circle: a 'puck' with the tub out of view this near it is the tub's own tape: ignored")
                puck = None
        act = next_circle_action(puck, basket, st)
        st.log.append({"action": act.kind, "value": round(act.value, 1), "why": act.why, "angle_deg": round(st.angle_deg), "puck": None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1)),
                       "basket": None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1))})
        say(f"circle: {act.why}" + (f" ({act.kind} {act.value:.1f}, {st.angle_deg:.0f} degrees round)" if act.kind not in ("found", "give_up") else ""))
        if on_step is not None:
            on_step(st.log)
        if act.kind == "found":
            return {"outcome": "found", "puck": puck, "basket": basket, "steps": st.log}
        if act.kind == "give_up":
            return {"outcome": act.why, "puck": None, "basket": basket, "steps": st.log}
        if act.kind != "arc" and hasattr(env.mover, "set_distance"):
            env.mover.set_distance(None if basket is None else float(basket.claw_in))
        if getattr(env.mover, act.kind)(act.value) == "fell":
            return {"outcome": "fell", "puck": None, "basket": None, "steps": st.log}
        if act.kind == "arc":
            st.angle_deg += abs(getattr(env.mover, "last_arc_deg", abs(act.value)))


class CameraStalled(Exception):
    """The camera gave no picture CAMERA_MISSES_MAX times in a row while he stood."""


class Fell(Exception):
    pass


class CameraHolder:
    """The run's camera, opened but never used until the attention pose with the claw raised (owner, 2026-11-23: no picture before that). `_ready`, `_cam` and `close` are what `RealEnv` needs."""

    def __init__(self, cam=None):
        import threading
        if cam is None:
            from ..config import settings
            from ..vision.snapshot import CameraSnapshotter
            cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump, exposure_check=True, idle_close_s=0, timeout_s=AFTER_PICTURE_TIMEOUT_S)                                                    # the shutter click stays on: the owner listens for it (the click was tried off as a test of the board's own up and made no difference)
        self._cam, self._error, self._ready = cam, None, threading.Event()
        self._ready.set()

    def open_port(self) -> bool:
        return bool(self._cam.open_port())

    def warm_up(self, tries: int = 3, say=print) -> bool:
        """Two throwaway pictures at the very start, with G2 still at rest (owner, 2026-11-23: the camera needs warming up, which is probably why the picture after the throw kept being skipped; a cold camera took 10 s for its first picture). The shutter click is off for these two so the
        first click the owner hears is the real picture. False when the camera never answered: the run does not start."""
        click = getattr(self._cam, "_click", True)
        try:
            self._cam._click = False
        except Exception:  # noqa: BLE001
            pass
        got = 0
        try:
            for i in range(tries * 2):
                try:
                    if self._cam.snapshot() is not None:
                        got += 1
                except Exception:  # noqa: BLE001
                    pass
                if got >= 2:
                    return True
                say(f"camera warm-up: no picture yet (try {i + 1})")
        finally:
            try:
                self._cam._click = click
            except Exception:  # noqa: BLE001
                pass
        return False

    def close(self) -> None:
        try:
            self._cam.close()
        except Exception:  # noqa: BLE001
            pass


def lob_end_lift() -> float:
    """The lift angle the lob's last frame leaves the arm at (from the script itself, so a changed script is followed)."""
    from . import lob, scripted_skill
    plan = scripted_skill.build_plan(scripted_skill.load_script(lob.SCRIPT), [0] * 8 + [20, 20, 30, 30, 30, 30, 30, 30], amount=lob.AMOUNT)
    return float(plan[-1]["frame"][1])


def merge_looks(seen: dict, offsets: dict):
    """One (basket, puck) from the claw look's pictures. `seen`: label to (basket reading or None, puck reading or None) in picture bearings; `offsets`: label to where that picture points, in degrees from straight ahead (+ right).
    The basket comes from the centre picture first, else the first other one; the puck likewise comes from the centre picture first (its bearing and distance), and only when the centre picture has none from the nearest side picture, which then says which side it was last seen on. Bearings are returned in the body frame (the picture's bearing plus its offset)."""
    from dataclasses import replace
    baskets, pucks = [], []
    for label, (basket, puck) in seen.items():
        off = offsets.get(label, 0.0)
        if basket is not None:
            baskets.append((0 if label == "centre" else 1, replace(basket, bearing_deg=basket.bearing_deg + off)))
        if puck is not None:
            pucks.append((0 if label == "centre" else 1, puck.claw_in, replace(puck, bearing_deg=puck.bearing_deg + off)))
    basket = min(baskets, key=lambda t: t[0])[1] if baskets else None
    puck = min(pucks, key=lambda t: t[:2])[2] if pucks else None                    # the centre picture's puck when it has one; the side pictures only say which side it was last seen on (owner, 2026-11-23: a 4 pixel false blob in the left picture beat the real puck seen in the centre one)
    return basket, puck


def retrieve(env, say=print, on_step=None, first=None) -> dict:
    """Search for the puck, walk to it and pick it up. Returns {"outcome": "retrieved" | a give-up reason | "fell", "steps": [...]}."""
    st = RState()
    while True:
        if first is not None:                      # the first step uses what the look after the throw just saw: no picture, no pause (owner, 2026-11-23)
            (basket, puck), first = first, None
        else:
            try:
                basket, puck = env.look()
            except Fell:
                return {"outcome": "fell", "steps": st.log}
        act = next_retrieval_action(puck, basket, st)
        st.log.append({"action": act.kind, "value": round(act.value, 1), "why": act.why, "puck": None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1)),
                       "basket_in": None if basket is None else round(basket.claw_in, 1)})
        say(f"retrieve: {act.why}" + (f" ({act.kind} {act.value:.1f})" if act.kind != "give_up" else ""))
        if on_step is not None:
            on_step(st.log)
        if act.kind == "give_up":
            return {"outcome": act.why, "steps": st.log}
        if act.kind == "pick":
            state = env.mover.forward(act.value) if act.value >= 0.5 else "ok"
            if state == "fell":
                return {"outcome": "fell", "steps": st.log}
            got = env.pick()
            st.picks += 1
            if got == "fell":
                return {"outcome": "fell", "steps": st.log}
            try:
                _b, still = env.look()
            except Fell:
                return {"outcome": "fell", "steps": st.log}
            gone = still is None or still.claw_in > GONE_WITHIN_IN
            st.log.append({"action": "picked_check", "value": 0.0, "why": "puck gone from the floor" if gone else "puck still on the floor", "puck": None if still is None else (round(still.claw_in, 1), round(still.bearing_deg, 1))})
            if gone:
                return {"outcome": "retrieved", "steps": st.log}
            if st.picks >= PICK_TRIES:
                return {"outcome": "pick_failed", "steps": st.log}
            continue
        if hasattr(env.mover, "set_distance"):
            env.mover.set_distance(None if puck is None else float(puck.claw_in))     # the turn picks pivot or arc by how far the puck is
        result = getattr(env.mover, {"scan": "scan", "pivot": "pivot", "nudge": "nudge", "forward": "forward"}[act.kind])(act.value)
        if result == "fell":
            return {"outcome": "fell", "steps": st.log}


def _rest(env, rec: dict) -> None:
    """Lay him down in rest once for this attempt (`rec["rested"]`): every way an attempt can end, other than a fall, ends with him lying, never standing about (owner, 2026-11-24: the legs sag after about 10 s and he fell on the next move). A fake environment without `lie_down` is left alone."""
    if rec.get("rested") or not hasattr(env, "lie_down"):
        return
    env.lie_down()
    rec["rested"] = True


def confirm_throw(env, rec: dict, say=print, persist=lambda state="running": None, first=None, look: str | None = None) -> dict:
    """The confirm look (owner, 2026-11-24): the after-throw look from about 16 inches cannot see into the clear tub (a puck inside is 0 to 5 coloured pixels there, 10 to 90 at 8 inches), so when it did not see the puck he walks up to about 8 inches of the tub (the line-up's own steps and
    buffer, aimed at CONFIRM_READING_IN). In the default "quick" mode the walk-up's last picture (claw down, taken at once) IS the confirm picture, read for a puck inside the tub the moment it is taken: nothing waits, a make lies down at once and a miss keeps moving, so he never stands idle (owner: the legs sag after about 10 seconds). In the "claw_up" mode he goes
    into the attention pose, raises the claw and takes ONE centred picture (`env.confirm_look()`: the shared claw look, centre only). Returns {"stop": a reason or None, "code", "basket", "puck"}: a puck inside is MADE (he lies down: the run ends), the tub not seen is NO_BASKET (lies down),
    nothing inside is a miss (`code` MISSED, `puck` the puck seen on the floor in that picture or None: the caller searches). Everything it saw goes into `rec["confirm"]` and the pictures are saved by `env`. `first`: the tub reading from the after-throw look (taken from the attention pose, so it is the accurate one), used for the walk-up's first decision with no picture.
    Two pictures in a row with no answer from the camera while he stands (CAMERA_MISSES_MAX) lie him down and stop the attempt."""
    look_mode = look or CONFIRM_LOOK
    say("confirm: walking up to look into the tub")
    t_stand = time.monotonic()
    quick = hasattr(env, "quick_confirm") and look_mode == "quick"
    misses = [0]

    def walk_look():
        reading = env.quick_basket()
        misses[0] = misses[0] + 1 if getattr(env, "last_quick_failed", False) else 0
        if misses[0] >= CAMERA_MISSES_MAX:
            raise CameraStalled()
        return reading
    try:
        n0 = getattr(env, "quick_count", 0)
        lu = bl.lineup(walk_look, env.mover, say=say, target_in=bl.CONFIRM_READING_IN, dist_tol=bl.CONFIRM_TOL_IN, align_tol=bl.CONFIRM_ALIGN_TOL_DEG, first=first)
        if lu["outcome"] == "aligned" and quick and getattr(env, "quick_count", 0) == n0:
            walk_look()                                                          # he was already in place on the first reading: the confirm picture is taken now
    except CameraStalled:
        say("confirm: no pictures from the camera while standing: lying down")
        _rest(env, rec)
        rec["confirm"] = {"walkup": {"outcome": "camera_stalled"}}
        persist()
        return {"stop": "no_picture", "code": None, "basket": None, "puck": None}
    rec["confirm"] = {"walkup": {"outcome": lu["outcome"], "steps": lu["steps"]}, "standing_s": round(time.monotonic() - t_stand, 1), "look": look_mode}        # how long he stood walking up and looking: the legs sag after about 10 s
    persist()
    if lu["outcome"] != "aligned":
        if lu["outcome"] != "fell":
            _rest(env, rec)
        return {"stop": lu["outcome"], "code": None, "basket": None, "puck": None}
    try:
        if quick:
            basket, floor, tub = env.quick_confirm()                              # the picture just taken, read at once (the finders take milliseconds): he does not wait on it
            env.confirm_picture_ok = bool(getattr(env, "last_quick", None))
        else:
            basket, floor, tub = env.confirm_look()
    except Fell:
        return {"stop": "fell", "code": None, "basket": None, "puck": None}
    if not getattr(env, "confirm_picture_ok", True):
        rec["confirm"]["look"] = {"code": "no_picture"}
        _rest(env, rec)
        say("confirm: no picture from the camera: stopping (not counted as a make)")
        persist()
        return {"stop": "no_picture", "code": None, "basket": None, "puck": None}
    code, words = classify_after(basket, floor, tub, confirm=True)
    rec["confirm"]["look"] = {"mode": look_mode, "code": code, "words": words, "tub": None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1), basket.width_px),
                              "floor_puck": None if floor is None else (round(floor.claw_in, 1), round(floor.bearing_deg, 1)),
                              "tub_puck": None if tub is None else (round(tub.x), round(tub.y), tub.count)}
    rec["after"]["first_look"] = {k: rec["after"].get(k) for k in ("code", "words", "puck", "basket")}
    rec["after"].update({"code": code, "words": words, "puck": rec["confirm"]["look"]["floor_puck"], "basket": None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1))})
    say(f"confirm: {code}: {words}")
    persist()
    if code in (bo.MADE, bo.NO_BASKET):
        _rest(env, rec)                                                       # a make: rest from the stand the look ended in; the run ends for the owner's reset
        return {"stop": "made" if code == bo.MADE else code, "code": code, "basket": basket, "puck": None}
    return {"stop": None, "code": code, "basket": basket, "puck": floor}


def _attempt_once(env, rec: dict, holding: bool, say=print, persist=lambda state="running": None) -> tuple[str | None, bool]:
    """ONE attempt: the throw, the look, and after a miss the retrieval and the line-up for the next throw. `rec` is the attempt's record (filled in as it goes). Returns (why it must stop or None to go on, whether he is holding the puck
    for the next throw). The stop reasons are those of `run_sequence`; "made" (a puck seen inside the tub from close up) and the other after-throw codes end a run for the owner's reset. The goal (goals/basket.py) and `run_sequence` both call this."""
    n = rec.get("attempt", 1)
    if not env.battery_ok():
        return "battery", holding
    say(f"attempt {n}: {'throw (holding the puck)' if holding else 'pick up and throw'}")
    t = env.throw(holding)
    rec["throw"] = {k: t.get(k) for k in ("ok", "fell", "path", "pack_pct")}
    if t.get("fell"):
        return "fell", holding
    if not t.get("ok"):
        return "throw_failed", holding
    holding = False
    persist()
    try:
        basket, puck = env.after_throw()
    except Fell:
        return "fell", holding
    if not getattr(env, "picture_ok", True):
        rec["after"] = {"code": "no_picture", "words": "The camera gave no picture after the throw, so I cannot say where it went."}
        _rest(env, rec)
        say("after the throw: no picture from the camera: stopping (not counted as a make)")
        persist()
        return "no_picture", holding
    code, words = classify_after(basket, puck)
    rec["after"] = {"code": code, "words": words, "puck": None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1)),
                    "basket": None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1))}
    rec["after"]["attention_hold_s"] = getattr(env, "attention_hold_s", None)
    rec["after"]["pictures"] = getattr(env, "look_readings", None)                    # what each picture of the look read (the merge keeps one basket and one puck)
    say(f"after the throw: {code}: {words}" + (f" (attention pose held {env.attention_hold_s} s)" if getattr(env, "attention_hold_s", None) is not None else ""))
    persist()
    confirm = code == bo.NOT_SEEN                                                  # a puck seen on the floor outside the tub is a certain miss: no confirm, straight to the pick-up (owner, 2026-11-24)
    if confirm and hasattr(env, "confirm_look"):
        # The puck was not seen from about 16 inches: inside the clear tub it is 0 to 5 coloured pixels there. Walk up to about 8 inches, look into it from the attention pose and read the picture (owner, 2026-11-24).
        res = confirm_throw(env, rec, say, persist, first=basket)
        if res["stop"]:
            return res["stop"], holding
        code, basket, puck = res["code"], res["basket"], res["puck"]
    elif code != bo.MISSED:
        _rest(env, rec)                                                       # no tub in view (or no confirm look to ask): rest, the run ends for the owner's check
        return code, holding

    def on_step(log, rec=rec):
        rec["retrieval"] = {"outcome": "running", "steps": list(log)}
        persist()
    if puck is None:
        # Looked into the tub from close up and the puck is not in it, and not on the floor in view: search round the tub (owner, 2026-11-24)
        def on_circle(log, rec=rec):
            rec["circle"] = {"outcome": "running", "steps": list(log)}
            persist()
        c = circle_search(env, say=say, on_step=on_circle)
        rec["circle"] = {"outcome": c["outcome"], "steps": c["steps"]}
        persist()
        if c["outcome"] != "found":
            rec["retrieval"] = {"outcome": "puck_not_found" if c["outcome"] != "fell" else "fell", "steps": []}
            if c["outcome"] != "fell":
                _rest(env, rec)                                                   # two laps without the puck (or the tub lost): the session ends at rest
            return ("fell" if c["outcome"] == "fell" else c["outcome"]), holding
        basket, puck = c["basket"], c["puck"]
    r = retrieve(env, say=say, on_step=on_step, first=(basket, puck))
    rec["retrieval"] = r
    persist()
    if r["outcome"] != "retrieved":
        return r["outcome"], holding
    lu = bl.lineup(env.quick_basket, env.mover, say=say)
    rec["lineup"] = {"outcome": lu["outcome"], "steps": lu["steps"]}
    persist()
    if lu["outcome"] != "aligned":
        return lu["outcome"], holding
    return None, True


def attempt_once(env, rec: dict, holding: bool, say=print, persist=lambda state="running": None) -> tuple[str | None, bool]:
    """ONE attempt (see `_attempt_once`). Whatever stops it, other than a fall, he is laid down in rest before this returns: a retrieval that gave up, a line-up that could not align, a camera that stalled, the battery. Standing idle after the attempt let the legs sag and he fell on the next move
    (2026-11-24). Returns (why it must stop or None to go on, whether he is holding the puck)."""
    why, holding = _attempt_once(env, rec, holding, say, persist)
    if why and why != "fell":
        _rest(env, rec)
    return why, holding


def run_sequence(env, max_attempts: int = MAX_ATTEMPTS, say=print, save=None) -> dict:
    """The attempts. Returns {"outcome": ..., "attempts": [...]}; the outcome says why it stopped: "made" (stop for the owner's reset), "max_attempts", "fell", "battery", "throw_failed", "circled_twice", "tub_lost", "no_basket",
    "basket_not_found", "could_not_align", "puck_not_found", "could_not_reach_puck", "too_near_the_basket", "pick_failed"."""
    attempts: list = []
    holding = False
    outcome = "max_attempts"

    def persist(state="running"):
        if save is not None:
            save({"outcome": state, "attempts": attempts})

    for n in range(1, max_attempts + 1):
        rec: dict = {"attempt": n, "holding": holding, "time": time.strftime("%H:%M:%S")}
        attempts.append(rec)
        persist()
        why, holding = attempt_once(env, rec, holding, say, persist)
        if why:
            outcome = why
            break
    return {"outcome": outcome, "attempts": attempts}


def write_log(result: dict, extra: dict | None = None, log_dir: str = LOG_DIR, path: str | None = None) -> str | None:
    try:
        d = os.path.expanduser(log_dir)
        os.makedirs(d, exist_ok=True)
        path = path or os.path.join(d, time.strftime("%Y%m%d_%H%M%S") + "_basket_run.json")
        with open(path, "w") as f:
            json.dump({**result, **(extra or {})}, f, indent=1, default=str)
        return path
    except OSError:
        return None


def reading_dict(r) -> dict | None:
    """A finder's reading as plain numbers for the picture log (a dataclass or any object with attributes; None stays None)."""
    if r is None:
        return None
    import dataclasses
    d = dataclasses.asdict(r) if dataclasses.is_dataclass(r) else dict(vars(r))
    return {k: (round(float(v), 2) if isinstance(v, float) else v) for k, v in d.items() if isinstance(v, (int, float, bool, str))}


def save_picture(run_stamp: str, attempt: int, label: str, jpeg: bytes, basket=None, floor=None, tub=None, extra: dict | None = None, log_dir: str = LOG_DIR) -> str | None:
    """Keep one look picture and what the finders read on it, for debugging and the next calibration (owner, 2026-11-24: "include the logging for each pic"). The picture goes to `<log_dir>/pictures/<run>/a<attempt>_<label>.jpg` on the Pi and one JSON line with the readings
    (the tub's tape columns, rim and base rows, width, distance, bearing; the puck on the floor; the puck inside the tub) to `pictures.jsonl` beside it. Never raises: a full disk must not stop a run. The pictures show the home: they stay on the Pi and the Mac and never go in the repository."""
    try:
        d = os.path.join(os.path.expanduser(log_dir), "pictures", run_stamp)
        os.makedirs(d, exist_ok=True)
        name = f"a{attempt:02d}_{label}.jpg"
        with open(os.path.join(d, name), "wb") as f:
            f.write(jpeg)
        with open(os.path.join(d, "pictures.jsonl"), "a") as f:
            f.write(json.dumps({"file": name, "time": time.strftime("%H:%M:%S"), "attempt": attempt, "label": label, "tub": reading_dict(basket), "floor_puck": reading_dict(floor), "tub_puck": reading_dict(tub), **(extra or {})}) + "\n")
        return os.path.join(d, name)
    except OSError:
        return None


class RealEnv:
    """G2 and his camera behind the `Env` interface: `throw`, `after_throw`, `look` (a quick picture), `quick_basket`, `pick`, `battery_ok` and `mover`. Built once per run on one open serial link."""

    def __init__(self, link, robot, looker, book=None, show_picture: bool = False):
        from . import basket_movers as bm
        self.link, self.robot, self.looker = link, robot, looker
        self.mover = bm.BasketMover(robot, book=book)
        self._cam = None
        self.show_picture, self.run_stamp, self.attempt = show_picture, time.strftime("%Y%m%d_%H%M%S"), 0
        self.quick_log: list = []
        self.picture_ok = True
        self.look_readings: dict = {}
        self.attention_hold_s = None
        self.confirm_picture_ok = True
        self.last_walkup = None
        self.last_quick, self.last_quick_failed = None, False
        try:
            looker._cam._timeout_s = AFTER_PICTURE_TIMEOUT_S              # a stalled camera ends a look in a few seconds, not eight a request
        except Exception:  # noqa: BLE001
            pass

    def _camera(self):
        from . import ball_chase as chase
        if self._cam is None:
            self._cam = chase._SnapshotCamera(self.looker._cam)
        return self._cam

    def battery_ok(self) -> bool:
        return bool(self.robot.battery_ok())

    def throw(self, holding: bool) -> dict:
        """The lob (a pick-up first unless he already holds the puck)."""
        from . import ball_chase as chase
        from . import lob, scripted_skill
        argv = [lob.SCRIPT, "--amount", str(lob.AMOUNT), "--gyro-off", "--no-prompt"]
        if not holding:
            argv += ["--pick", "--pick-gap", str(lob.PICK_GAP_S)]            # no grip picture between the pickup and the throw (owner, 2026-11-23: it should not be happening and is probably why the board stopped taking the throw)
        a = scripted_skill.parser().parse_args(argv)
        self.attempt += 1
        out = scripted_skill.play(a, scripted_skill.load_script(a.script), {}, link=self.link, robot=self.robot, looker=None, rest_after=False)
        self.robot.posture = "stand"
        self.robot._claw = (0.0, lob_end_lift())                            # the arm is where the throw's last frame left it (125 deg), not at 0: the move to the look angle starts from there
        res = out.get("res") or {}
        out["fell"] = bool(out.get("fell")) or res.get("verdict") == "fell"
        return out

    def after_throw(self):
        """The ball goal's own claw look, unchanged and complete (`claw_survey.run_claw_look`: `sit_down`, the claw up in two steps, a settle, the pictures left, right and centre, the claw down, then its own eased back-legs-first stand-up from the attention pose), read by the basket and puck finders and merged into
        one reading each. The sequence (owner, 2026-11-23): attention pose, stand-up, then rest if he made the shot (`lie_down()` from the stand, the standard lie-down) or start walking at once if he has to fetch the puck. `expect_lob_end()` tells the look's move gate that the lob's pitched end pose is not a sag
        (the owner approved that exception). He is STANDING when this returns. The lie-down from the attention pose (the first versions of this step) flipped him 16 of 16 times (the real walk log). With show_picture the centre picture is printed (base64, one line), never saved on the Pi."""
        from . import ball_chase as chase
        from . import claw_survey
        from ..vision import basket_finder as bf
        from ..vision import puck_finder as pf
        cam, seen = self._camera(), {}
        left = chase.CLAW_PAN_DEG if chase.CLAW_PAN_SIGN == "left" else -chase.CLAW_PAN_DEG
        self.picture_ok = False
        self.look_readings = {}

        def snapshot(label):
            t_start = time.monotonic() - t_look
            jpeg = cam.look()
            t_end = time.monotonic() - t_look
            if jpeg:
                basket = bf.find_basket(jpeg)
                seen[label] = (basket, pf.find_puck(jpeg, basket))
                b_, p_ = seen[label]
                save_picture(getattr(self, "run_stamp", "run"), getattr(self, "attempt", 0), f"after_{label}", jpeg, b_, p_, pf.find_puck_in_tub(jpeg, basket), {"t_s": round(time.monotonic() - t_look, 2)})
                self.look_readings[label] = {"t_s": (round(t_start, 2), round(t_end, 2)), "basket": None if b_ is None else (round(b_.claw_in, 1), round(b_.bearing_deg, 1), b_.width_px),
                                             "puck": None if p_ is None else (round(p_.claw_in, 1), round(p_.bearing_deg, 1), p_.width_px, round(p_.x), round(p_.y))}
                if label == "centre":
                    self.picture_ok = True
                    if self.show_picture:
                        import base64
                        print(f"AFTER_PICTURE {self.attempt} {base64.b64encode(jpeg).decode()}", flush=True)
            return jpeg
        self.robot.expect_lob_end()
        t0 = t_look = time.monotonic()
        state = claw_survey.run_claw_look(self.link, snapshot, "centre", robot=self.robot)
        self.attention_hold_s = round(time.monotonic() - t0, 1)
        if state != "ok" and getattr(self.robot, "last_fall", None):
            raise Fell()
        return merge_looks(seen, {"look_left": -abs(left), "look_right": abs(left), "centre": 0.0})

    def confirm_look(self):
        """The confirm look: the shared claw look with the centre picture only (`claw_survey.run_claw_look(..., centre_only=True)`: stand, the attention pose, the claw up in two steps, a settle, ONE picture, the claw down, the eased stand-up), read three ways: the tub, a puck on the floor outside it and a puck inside it.
        Returns (tub reading or None, floor puck or None, puck inside or None). He is STANDING when it returns. The picture and every reading go to the picture log (`save_picture`). Sets `confirm_picture_ok`."""
        from . import claw_survey
        from ..vision import basket_finder as bf
        from ..vision import puck_finder as pf
        cam, got = self._camera(), {}
        self.confirm_picture_ok = False

        def snapshot(label):
            jpeg = cam.look()
            if jpeg:
                basket = bf.find_basket(jpeg)
                got[label] = (basket, pf.find_puck(jpeg, basket), pf.find_puck_in_tub(jpeg, basket))
                self.confirm_picture_ok = True
                save_picture(getattr(self, "run_stamp", "run"), getattr(self, "attempt", 0), "confirm", jpeg, *got[label], {"walkup_final": getattr(self, "last_walkup", None)})
            return jpeg
        state = claw_survey.run_claw_look(self.link, snapshot, "centre", robot=self.robot, centre_only=True)
        if state != "ok" and getattr(self.robot, "last_fall", None):
            raise Fell()
        return got.get("centre", (None, None, None))

    def lie_down(self) -> None:
        """The standard lie-down from the stand (a make: nothing else to do)."""
        from . import ball_chase as chase
        chase.ensure_rest(self.link)
        self.robot.posture, self.robot._claw = "rest", (0.0, 0.0)

    def _ready_to_move(self) -> None:
        """From the attention pose with the claw up: the claw down, laid in rest, then the eased stand-up from rest (owner, 2026-11-23: a stand-up straight from the attention pose is a fall every time). Standing already: nothing."""
        posture = getattr(self.robot, "posture", "stand")
        if posture == "attention":
            if self.robot.rest_then_stand() == "fell":
                raise Fell()
        elif posture == "rest":
            if self.robot.stand_up_from_rest() == "fell":                       # the eased stand-up from rest (stand_up() sends nothing in the standing flow)
                raise Fell()

    def _quick(self, by: str):
        """One quick picture with the claw down: (basket reading, puck reading), the picture saved with the readings for the next fit."""
        from ..vision import basket_finder as bf
        from ..vision import puck_finder as pf
        self._ready_to_move()
        cam = self._camera()
        jpeg = cam.look()                                                # no forced re-metering: the warm-up metered the light
        self.last_quick_failed = not jpeg
        if not jpeg:
            self.last_quick = None
            return None, None
        basket = bf.find_basket(jpeg)
        puck = pf.find_puck(jpeg, basket, by=by)
        tub_puck = pf.find_puck_in_tub(jpeg, basket)
        self.last_quick = (basket, puck, tub_puck)                       # what the confirm step reads when this was its picture (`quick_confirm`)
        n = len(self.quick_log) + 1
        d = os.path.join(os.path.expanduser(LOG_DIR), "quick", self.run_stamp)
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"q{n:02d}.jpg"), "wb") as f:
                f.write(jpeg)
        except OSError:
            pass
        self.last_walkup = None if basket is None else (round(basket.claw_in, 1), round(basket.width_px))
        save_picture(getattr(self, "run_stamp", "run"), getattr(self, "attempt", 0), f"quick{n:02d}", jpeg, basket, puck, tub_puck, {"by": by})
        self.quick_log.append({"n": n, "time": time.strftime("%H:%M:%S"),
                               "basket": None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1), basket.width_px),
                               "puck": None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1), puck.width_px, round(puck.y))})
        return basket, puck

    @property
    def quick_count(self) -> int:
        return len(self.quick_log)

    def quick_confirm(self):
        """The confirm step's reading from the last quick picture (claw down, taken at the end of the walk-up): (tub, puck on the floor, puck inside the tub), read when the picture was taken, so nothing waits."""
        return self.last_quick if self.last_quick is not None else (None, None, None)

    def look(self):
        """The retrieval's look: a quick claw-down picture, as the ball goal takes while it walks up (the puck's distance from its width)."""
        return self._quick("width")

    def quick_basket(self):
        """The line-up's look: a quick claw-down picture, the basket's reading or None."""
        return self._quick("width")[0]

    def pick(self):
        from .catapult import pick_up
        ok = pick_up(self.link, seen=[])
        self.robot.posture = "stand"
        return "ok" if ok else "failed"


def main(argv: list | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="The full basket sequence on G2 (hands near, the voice service stopped, G2 at rest with the puck touching the claw tip and the basket 16 inches out).")
    ap.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    ap.add_argument("--look-only", action="store_true", help="no throw: stand up from rest, take the claw look once, print what each picture read (basket and puck distance, bearing and picture position), lie down; to check which side the look's pictures point")
    ap.add_argument("--confirm-only", action="store_true", help="no throw: stand up from rest, walk up to about 8 inches of the tub, take the confirm look, print what the finders read (the tub, a puck on the floor, a puck inside it), lie down; for checking the walk-up and the close look with the puck placed by hand (G2 at rest, the tub about 16 inches out)")
    ap.add_argument("--claw-up", action="store_true", help="with --confirm-only: use the attention-pose confirm look (claw raised, one centred picture) instead of the walk-up's own last picture")
    ap.add_argument("--circle-only", action="store_true", help="no throw: stand up from rest, circle the tub (the puck NOT in view: put it behind the tub or out of the room) looking for the puck, up to two laps, print the steps, lie down; for checking the circling movement (the tub about 16 inches out)")
    ap.add_argument("--show-picture", action="store_true", help="after each throw print the picture of the floor (JPEG, base64, one line) for the person running it; never saved on the Pi")
    a = ap.parse_args(argv)
    from . import ball_chase as chase
    from . import chase_pace
    from ..link import imu_print
    from ..link.serial_link import SerialLink
    from ..power import battery
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok or not imu_print.board_answers(link):
        print("not started: the pack gate failed or the board sent no motion data")
        return
    looker = CameraHolder()
    if not looker.open_port() or not looker.warm_up():
        print("not started: the camera did not open and warm up (check its USB plug); nothing was moved")
        looker.close()
        return
    robot = chase.SerialRobot(link)
    result = {"outcome": "not_run", "attempts": []}
    path = os.path.join(os.path.expanduser(LOG_DIR), time.strftime("%Y%m%d_%H%M%S") + "_basket_run.json")
    env = None
    try:
        env = RealEnv(link, robot, looker, book=chase_pace.book_for_now(save=False), show_picture=a.show_picture)
        if a.look_only:
            env.attempt = 0
            if robot.stand_up_from_rest() == "fell":
                raise Fell()
            basket, puck = env.after_throw()
            print(f"LOOK offsets: look_left -{chase.CLAW_PAN_DEG:.0f}, look_right +{chase.CLAW_PAN_DEG:.0f}, centre 0 (degrees, + to G2's right)")
            for label, r in env.look_readings.items():
                print(f"LOOK {label}: basket {r['basket']} puck {r['puck']} picture asked at {r['t_s'][0]} s, answered at {r['t_s'][1]} s after the look began   (distance in, bearing deg, width px[, x, y])")
            print("LOOK merged: basket", None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1)), "puck", None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1)))
            env.lie_down()
            return
        if a.confirm_only or a.circle_only:
            env.attempt = 0
            if robot.stand_up_from_rest() == "fell":
                raise Fell()
            rec = {"attempt": 0, "after": {}}
            if a.confirm_only:
                res = confirm_throw(env, rec, say=print, look="claw_up" if a.claw_up else None)
                print("CONFIRM", json.dumps({"stop": res["stop"], "code": res["code"], "confirm": rec.get("confirm")}, default=str))
            else:
                c = circle_search(env, say=print)
                print("CIRCLE", c["outcome"], f"after {len(c['steps'])} step(s)", None if c["puck"] is None else (round(c["puck"].claw_in, 1), round(c["puck"].bearing_deg, 1)))
            env.lie_down()
            print("pictures kept in", os.path.join(os.path.expanduser(LOG_DIR), "pictures", env.run_stamp))
            return
        result = run_sequence(env, a.max_attempts, save=lambda r: (result.update(r), write_log(r, {"pack_pct_start": pct, "quick": env.quick_log}, path=path)))
    except KeyboardInterrupt:
        result["outcome"] = "interrupted"
    finally:
        looker.close()
        try:
            link._end_quiet()
        except Exception:  # noqa: BLE001
            pass
        chase.ensure_rest(link)
    path = write_log(result, {"pack_pct_start": pct, "quick": env.quick_log if env else []}, path=path)
    print("RESULT", result["outcome"], f"after {len(result['attempts'])} attempt(s); logged {path}")


if __name__ == "__main__":
    main()
