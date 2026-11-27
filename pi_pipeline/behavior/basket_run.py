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
from ..vision import puck_close
from ..vision.object_finder import ObjectReading

MAX_ATTEMPTS = 5
MAX_RETRIEVAL_STEPS = 30             # walking steps (pivots, turns, walks, pick-ups); the pivot scans have their own cap
MAX_SCANS = 30                        # about two full circles of scan pivots in all, however often the puck is seen and lost (owner, 2026-11-23: scans must not use up the walking steps)
BLIND_STEP_IN = 1.5                   # a puck at the claw tip (its blob cut off at the bottom of the picture): the finder's distance is wrong, so one short blind step, then the pick-up
PICK_TRIES = 6
SCAN_STEP_DEG, SCAN_MAX_DEG = 27.0, 360.0
ALIGN_DEG = 6.0                      # the puck's bearing must be inside this before the last walk (a pick-up window is about 1 inch wide)
PICK_STAND_IN = 8.0                  # the puck this far from the claw tip (as the finder reads it) is where the last walk starts: a forward walk moves about 8 inches whatever is asked (12 logged walks, 2026-11-25) and the pick-up wants the puck at the claw tip. 8 inches, not 9.5: in the claw-down picture a puck 9 inches off sat at row 85, one row above the finder's floor window (84), and he lost it after the back-up; at 8 inches it is at about row 89, inside. Nearer than PICK_STAND_IN - PICK_STAND_TOL_IN he backs up (back-ups are finer), looks again, squares up to the puck (the back-up curves him aside, so the turn onto it comes before any walk) and only then walks; farther than PICK_STAND_IN + PICK_STAND_TOL_IN he walks up
PICK_STAND_TOL_IN = 1.5
PICK_BAND_MIN_IN, PICK_BAND_MAX_IN = 4.5, 11.0     # the last walk and the pick-up from a puck read anywhere in this band (was 6.5 to 9.5, 3 inches wide). 2026-11-27 runs: a back-up moved him 6 to 9 inches and a forward walk 5 to 8 whatever was asked, so no step could land in a 3 inch band and he went back, turn, forward, back for 50 steps until the puck was lost. The last walk's ask is the puck's distance less PICK_UNDERSHOOT_IN and it moves him about 2.4 inches more than asked (a walk of 5.6 left the puck at the jaw in all three tries), so from anywhere in the band it ends in the same place
FORWARD_LEAVES_IN = 9.5            # a puck beyond the band: walk up so that about this much is left (the walk moves at least 5 inches), which lands inside the band
PICK_AT_TIP_IN = 3.0


def pick_direct_max_in() -> float:
    """How far from the claw tip a centred puck can be for the pick-up to take it without the back-up and the 8 inch last walk. Default PICK_AT_TIP_IN (no change); `G2_PICK_DIRECT_MAX_IN=4.5` tries it (2026-11-27 run: four times a centred puck 3.4 to 4.7 inches out was backed away from, each cycle 20 seconds and a sideways drift). Measure pickF's reach (picks from 3, 4 and 5 inches) before changing the default."""
    try:
        return float(os.environ.get("G2_PICK_DIRECT_MAX_IN", PICK_AT_TIP_IN))
    except ValueError:
        return PICK_AT_TIP_IN
APPROACH_TOL_IN = 1.5
APPROACH_STEP_MAX_IN = 10.0
PICK_UNDERSHOOT_IN = 1.5             # the last walk stops this short of the finder's distance: the puck must be at the claw tip, and a puck pushed away is lost
VANISH_NEAR_IN, VANISH_BACKS_MAX = 22.0, 3       # a puck seen in one look and not in the next (after a turn or a walk) is lost from view, not gone: back up and look again, up to VANISH_BACKS_MAX times a retrieval, before any pivot scan (owner, 2026-11-27: "if he sees the puck, moves forward, then doesn't see the puck, the answer is to back up and re-acquire"). Was 5.5 inches (under the claw, 2026-11-27 9:34 run: lost at 3.0 inches after a small turn, then 14 scans); the 16:18 basket run lost it at 10.4 inches after a nudge and scanned blind seven times, about 45 seconds standing. 22 inches is the finder's far limit; the basket goal and the pick-up drill share this retrieval
CLOSE_FLOOR_BEARING_DEG = 8.0               # the floor finder's bearing, in the picture the close finder calls "at the spot", is not to be this far off
CLOSE_REAPPROACH_MAX, CLOSE_REAPPROACH_BACK_IN = 2, 4.0   # the puck is not at the spot after the close look's tries (or not seen there): back up this far and look again instead of picking blind, this many times a retrieval (2026-11-27 run: blind picks left the puck beside the claw)
HELD_BASE_ROW_MIN, HELD_CHECK_BACK_IN = 200, 3.0   # after the pick-up a puck in the jaw reads 57 to 65 px wide with its base at row 200 or lower; otherwise he backs off this far and looks, and a puck seen on the floor means it was missed
CLOSE_ALIGN_TRIES = 2               # after the last walk: look at the puck against the pick-up spot (vision/puck_close.py, from the owner's 2 inch pictures) and correct at most this many times before the pick-up (each look is time on his feet; owner, 2026-11-26: "this is how he should try to get aligned")
CLOSE_FORWARD_IN, CLOSE_BACK_IN = 0.0, 1.0   # the corrections for a puck farther or nearer than the spot. A back-up of 1 second moves about 2 inches. No forward correction yet (0): a forward walk moves about 8 inches whatever is asked, which would push the puck away; it needs the rows-to-inches pictures (1, 3, 4 and 6 inches) and a measured short step
CLIPPED_ROW_PX = 210                 # a puck whose base reaches the crop (rows past BOTTOM_ROW 212 are not read) is cut off; see CLIPPED_UNDER_JAW_ROW_PX for narrow blobs
CLIPPED_UNDER_JAW_ROW_PX = 205                 # a puck whose base reaches this row is at the bottom of the picture, partly behind the claw jaw (the jaw tip is near row 205): its base row and column are cut off, so the close look neither backs up for it nor turns for a small offset (2026-11-27 run: three last walks left it at row 211, the close look turned the puck from 98 to 81 px, then read nothing and backed up, and the third try, picked blind from there, got it)
CLIPPED_COL_TOL_PX = 30              # the sideways offset a clipped puck may have before the close look turns him (the pick-up window is about 1 inch; 20 px there is under half an inch)
CLIPPED_MIN_HEIGHT_PX = 20          # ... and at least this tall (a glint at the bottom rows is 4 or 5 px high; the puck behind the jaw 41)
CLIPPED_UNDER_JAW_IN = 8.0           # a narrow blob at the bottom rows after a last walk, with the puck last read within this many inches, is the puck mostly hidden behind the jaw, not clutter
GONE_WITHIN_IN = 12.0                # after a pick-up a puck still seen on the floor this near means the pick-up missed
CONFIRM_LOOK = "quick"               # "quick": the walk-up's own last picture (claw down, taken at once, read at once: no attention-pose cycle, no standing about) is the confirm picture (owner, 2026-11-24: "he can just walk up and take a fast picture, but he can't be standing idle for a long time afterwards"); "claw_up": the attention-pose look as first built (`env.confirm_look()`)
CAMERA_MISSES_MAX = 2                # this many pictures in a row with no answer while he stands in the walk-up: he lies down and the attempt stops (a stalled camera must not leave him standing: the legs sag after about 10 s)
CIRCLE_RADIUS_IN = 16.0              # the circle's radius as the finder reads it, used at the peeks (too tight was the problem on the first arc run, never too wide: owner, 2026-11-24)
CIRCLE_MIN_IN = 10.0                 # nearer than this (as read) he backs off before anything else (the first goal run ended a leg 4.5 inches from the tub)
CIRCLE_ARC_DEG = 45.0                # one wide arc's heading change: 8 arcs a lap
CIRCLE_PIVOT_CHUNK_DEG = 54.0         # one pivot move is two cycles at most and turns him about 45 degrees (owner, 2026-11-25: about 22 a cycle; docs/rl/real-walk-log.md) (ball_chase.PIVOT_MAX_CYCLES, about 45 to 52 degrees by the owner's eye) and the mover caps an ask at 60: a bigger ask is made of moves this size, one after the other (owner, 2026-11-25: the 81 degree turn to put the tub beside him only turned 45, and the arc was too tight; the peek and the turn back asked for 108 and got 54 too)
CIRCLE_SQUARE_ASK_DEG = 108.0          # what the first pivot asks for to turn him about 90 degrees: four cycles of about 22 each (two moves of two cycles; one move of two turned only about 45)
CIRCLE_SQUARE_DEG = 90.0             # facing the tub, this pivot puts it beside him (checked by the gyro: the tub is out of the picture at 90 degrees)
CIRCLE_STRAIGHT_IN = 0.0             # no straight walk after an arc (owner, 2026-11-24): the arc is measured at about 15 inches of radius, already the circle we want, and on the simulated floor the 6 inches that widened a guessed 9 inch arc threw it out to 11 to 28 inches and lost the tub (without it 12.5 to 18); a number above 0 brings the walk back
CIRCLE_PEEK_EVERY = 0                # no peeks (owner, 2026-11-25: the circle test ran 23 arcs and about two laps with the forward picture as the only check, and the peek was what lost the tub): the forward picture after each arc is the scan, a tub in it turns him outward, a puck in it ends the search; N > 0 peeks (turns toward the tub, reads its distance and the floor) every N arcs
CIRCLE_TIGHT_MIN_TURN_DEG, CIRCLE_TIGHT_MAX_TURN_DEG = 15.0, 60.0   # the tub in the forward picture means the circle is too tight: turn away by how far forward it stands (it should be beside him), at least and at most this
CIRCLE_PEEK_DEG = 60.0               # the first peek: turn this far toward the tub, look, and turn back; after that the peek turns by where the last one found the tub (CIRCLE_PEEK_TARGET_DEG off his nose), because on the simulated floor 60 degrees left the tub out of the picture on almost every peek
CIRCLE_PEEK_TARGET_DEG = 25.0        # where the peek aims to put the tub, off his nose (the camera sees about 35 degrees each side)
CIRCLE_PEEK_MIN_DEG, CIRCLE_PEEK_MAX_DEG = 30.0, 90.0
CIRCLE_SEEN_TURN_DEG = 15.0        # the tub in the forward picture after an arc at all (owner, 2026-11-24: he plowed through the tub): turn outward this much; nearer his nose or near, by how far forward it stands (CIRCLE_TIGHT_MIN_TURN_DEG up to CIRCLE_TIGHT_MAX_TURN_DEG)
CIRCLE_TIGHT_BEARING_DEG = 15.0      # the tub in the forward picture is too tight only when it is this near his nose (an arc toward the tub brings it to about 35 degrees on a good circle: 2026-11-24) or nearer than CIRCLE_TIGHT_NEAR_IN
CIRCLE_TIGHT_NEAR_IN = 12.0
BLIND_BURSTS, BLIND_BURST_IN = 4, 6.0     # no tub in the after-throw look: walk forward this many inches (a walk moves about 8 whatever is asked) and look again, up to this many times, before giving up (owner, 2026-11-25: the tub is always right in front of him at the start, he may just need to get closer to see it)
CIRCLE_START_IN, CIRCLE_START_TOL_IN, CIRCLE_START_MIN_IN, CIRCLE_START_WALKS, CIRCLE_START_STEP_IN = 11.0, 8.0, 8.0, 5, 3.0   # CIRCLE_START_TOL_IN 3.0 to 8.0 (owner, 2026-11-27): the pivot and arc start from anywhere up to CIRCLE_START_IN + the tolerance (19 inches, was 14) so the line-up's distance need not be precise (the circle's radius is 16 inches anyway). Before that, the circle starts close (owner, 2026-11-24): face the tub, walk up to about CIRCLE_START_IN of it (within 10 to 12.5 inches), then pivot 90 degrees away and arc toward it; nearer than CIRCLE_START_MIN_IN (the finder's limit) at the start he backs off
CIRCLE_FIND_FAR_IN, CIRCLE_FIND_BACK_IN = 22.0, 4.0     # the tub lost at the start after being read at or under this many inches: back up this far and look (walking forward closer to a tub that is too near rammed it on 2026-11-24); over it or never seen: walk forward
CIRCLE_FIND_FORWARD_IN, CIRCLE_FIND_FORWARD_MAX = 6.0, 3   # the tub not in view at the start: walk forward this far and look again, up to this many times, before any pivoting (owner, 2026-11-24)
CIRCLE_LOST_MAX_DEG = 180.0          # the most he pivots looking for a tub that is out of view (owner, 2026-11-24: no spinning round; 360 degrees of blind pivots ended two test runs), then he lies down
CIRCLE_FACE_TOL_DEG = 8.0            # facing the tub: its bearing inside this before the circle starts
CIRCLE_RADIUS_GAIN = 2.0             # degrees of extra turn away from (or toward) the tub per inch the radius is off (clamped)
CIRCLE_CORRECTION_MAX_DEG = 25.0   # outward (too near); a circle too wide is corrected by at most CIRCLE_WIDE_MAX_DEG the other way
CIRCLE_WIDE_MAX_DEG = 8.0
CIRCLE_LOST_STEP_DEG = 30.0          # the tub out of view: pivot this much toward its side
CIRCLE_TAPE_ASPECT = 2.5             # the tub's tape seen from close up is a wide thin red blob (about 4 to 1 or wider, 20 by 5 pixels on 2026-11-25); a puck is about 1 to 1 (12 by 9 and 18 by 15 pixels): only a blob this wide for its height is taken for the tape
CIRCLE_TAPE_GUARD_IN = 12.0          # a "puck" in view with the tub out of view, when the tub was last read nearer than this, is the tub's own red tape seen from too close, not a puck (the first goal run chased it for 22 scans)
CIRCLE_MAX_LAPS = 2.0                # more than two laps without the puck ends the session (owner, 2026-11-24)
CIRCLE_MAX_STEPS = 150
CIRCLE_STRAIGHT_GAIN = 0.0           # inches of straight walk added per inch the last peek read the radius under CIRCLE_RADIUS_IN (taken away when over). Off: on the simulated floor 0.5 and 0.8 made the circle worse with a peek every third arc (nearest 3.3 and 2.1 inches against 11) and gained nothing with a peek every arc, because the turn back after each peek (CIRCLE_RADIUS_GAIN) already steers; turn it on only if the circle test's log shows the turn back is not enough
CIRCLE_STRAIGHT_MIN_IN, CIRCLE_STRAIGHT_MAX_IN = 2.0, 14.0
CIRCLE_ANGLE_SCALE = 1.0             # the lap is counted from each arc's counted degrees times this: the degrees ASKED now (the arc is timed; the gyro read 0.15 of a real right turn and 1.8 of a left one, 2026-11-24), the real turn fitted from the circle test's log
CIRCLE_BAND_IN = (12.0, 22.0)        # a peek's distance outside this is a soft failure of the circle test (22 is the finder's far limit)
CIRCLE_TEST_LAPS_IN_A_ROW = 3        # the circle test passes when this many clean laps follow one another (owner, 2026-11-24)
STAND_IDLE_REST_S = 6.0               # a look that gets no picture while he has stood this long with no leg move lies him down instead of waiting for the next try (owner, 2026-11-24: standing still more than about 10 s sags the legs; the camera stalls left him standing 12 to 13 s); the next look or move stands him up from rest
CIRCLE_TEST_MINUTES = 4.0            # the circle test's first time cap (owner, 2026-11-24)
LOG_DIR = "~/g2_runs/basket_run"
AFTER_PICTURE_TIMEOUT_S = 8.0          # the camera's wait for one picture of the claw look (after the throw, the confirm look): the first picture after the claw pans or moves can take 4 to 6 s, and with 4 s the look's right-hand picture was lost in both goal runs of 2026-11-25 (owner saw no picture on the right)
QUICK_PICTURE_TIMEOUT_S = 4.0          # the wait for a quick claw-down picture while he walks or circles (owner, 2026-11-24: an 8 s wait standing sagged the legs; each look's own time is logged as `look_s`)


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
    last_seen_in: float | None = None   # the puck's last reading (inches from the claw tip): one lost from close range is under the claw, not gone
    vanish_backs: int = 0
    reapproach: int = 0              # times he backed off and looked again because the puck was not at the pick-up spot (instead of picking blind)
    log: list = field(default_factory=list)


def next_retrieval_action(puck, basket, st: RState) -> RAction:
    """The next step toward the puck from a fresh look (a PuckReading or None, and the basket reading or None in the same picture).
    The tub's nearness never ends the retrieval (owner, 2026-11-27: two runs gave up with the puck a few inches from the claw and the tub 11 inches off; the puck is never dangerously close to it): the basket reading is only logged."""
    if st.steps >= MAX_RETRIEVAL_STEPS:
        return RAction("give_up", 0.0, "could_not_reach_puck")
    if puck is None and st.last_seen_in is not None and st.last_seen_in <= VANISH_NEAR_IN and st.vanish_backs < VANISH_BACKS_MAX:
        st.vanish_backs += 1
        st.steps += 1
        seen, st.last_seen_in = st.last_seen_in, None
        return RAction("back", CLOSE_REAPPROACH_BACK_IN, f"puck lost from {seen:.1f} in out: back up to see it again")
    if puck is None:
        if st.scanned_deg >= SCAN_MAX_DEG or st.scans >= MAX_SCANS:
            return RAction("give_up", 0.0, "puck_not_found")
        st.scanned_deg += SCAN_STEP_DEG
        st.scans += 1
        return RAction("scan", SCAN_STEP_DEG * st.scan_dir, "puck not in view: pivot scan")
    st.scanned_deg = 0.0
    d, b = float(puck.claw_in), float(puck.bearing_deg)
    st.last_seen_in = d
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
    if d > PICK_BAND_MAX_IN:
        st.steps += 1
        return RAction("forward", min(APPROACH_STEP_MAX_IN, d - FORWARD_LEAVES_IN), "walk up to the puck")
    if pick_direct_max_in() > PICK_AT_TIP_IN and d <= pick_direct_max_in():                 # near and centred: the pick-up reaches it (G2_PICK_DIRECT_MAX_IN, off by default: the reach of pickF is still to be measured)
        return RAction("pick", BLIND_STEP_IN, "puck near and centred: the pick-up reaches it, no back-up")
    if PICK_AT_TIP_IN <= d < PICK_BAND_MIN_IN:                                              # (nearer than PICK_AT_TIP_IN it is at the claw tip already: no walk, the pick-up)
        st.steps += 1
        return RAction("back", PICK_STAND_IN - d, "too near the puck for the last walk (it moves about 8 inches): back up")
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
    phase: str = "face"              # "face" (find the tub and face it) -> "arc" (a wide turn) -> "straight" (a walk that widens the circle) -> "glance" (the forward picture: the tub in it means too tight) -> "arc" ...; every CIRCLE_PEEK_EVERY arcs: "peek" (turn toward the tub) -> "look" (read it, correct, turn back) -> "arc"
    arcs: int = 0
    last_d: float | None = None      # the last tub distance read
    log: list = field(default_factory=list)
    max_laps: float = CIRCLE_MAX_LAPS    # the goal ends the session after this many laps; the circle test sets it high and ends on the clock or a streak
    peek_every: int = CIRCLE_PEEK_EVERY  # 0 = never peek (the forward picture is the only check); the goal's own is a setting to fit from the circle test
    max_steps: int = CIRCLE_MAX_STEPS
    streak_target: int = 0               # clean laps in a row that end the search as "passed" (the circle test only; 0 = off)
    events: list = field(default_factory=list)   # one record per arc: asked and gyro degrees, the straight walk, what the forward picture and the peek read
    lost_first: int = 1                  # which way the lost-tub sweep goes first (+1 toward the tub's side, -1 back the way he came)
    start_walks: int = 0                 # walks made up to the tub at the start
    find_back: int = 0                   # back-ups made at the start after the tub was seen and then lost near
    find_forward: int = 0                # forward steps made so far looking for the tub at the start
    peek_deg: float = CIRCLE_PEEK_DEG    # how far the next peek turns toward the tub (learned from the last one)
    peek_turn: float = 0.0               # the turn made toward the tub in this peek so far (the peek plus any lost-tub steps)
    looks: list = field(default_factory=list)   # every look: the phase, the arc, how long the picture took and whether one came (what standing still waiting for the camera cost)
    d_arc: int = -99                     # the arc after which last_d was read by a peek (a reading a few arcs old steered the straight walk the wrong way on the simulated floor)
    soft: list = field(default_factory=list)     # what spoiled a lap: back-offs, a tub in the forward picture, a peek outside the band, the tub lost

    @property
    def needs_look(self) -> bool:
        return self.phase in ("face", "glance", "look")

    def lap_now(self) -> int:
        return int(self.angle_deg // 360.0)

    def note_soft(self, kind: str, **kw) -> None:
        """A soft failure: it spoils the lap it happened in (before the first arc it spoils none: that is the start-up)."""
        self.soft.append({"kind": kind, "angle": round(self.angle_deg, 1), "lap": self.lap_now() if self.arcs else -1, **kw})

    def cur(self) -> dict:
        return self.events[-1] if self.events else {}


def _looks_like_tape(puck) -> bool:
    """The tub's own red tape read as a puck: a blob much wider than it is tall. A reading with no size (a test's stand-in) is taken for the tape, as before. A puck on the floor is about as tall as it is wide (2026-11-25: two real pucks at 7.9 and 5.3 inches were ignored as tape and he circled on past a puck right in front of him)."""
    w, h = getattr(puck, "width_px", None), getattr(puck, "height_px", None)
    if not w or not h:
        return True
    return float(w) / float(h) >= CIRCLE_TAPE_ASPECT


def pivot_chunks(degrees: float) -> list:
    """A pivot of `degrees` as moves of whole cycles, two cycles (CIRCLE_PIVOT_CHUNK_DEG) at most each, in the same direction: one pivot move turns two cycles at most and the mover caps an ask at 60 degrees (a 108 degree ask used to turn about 50). 108 is [54, 54], 81 is [54, 27], 27 is [27]."""
    cycles = max(1, round(abs(degrees) / bl.PIVOT_CYCLE_DEG))
    per_move = max(1, round(CIRCLE_PIVOT_CHUNK_DEG / bl.PIVOT_CYCLE_DEG))
    sign = 1.0 if degrees >= 0 else -1.0
    out = []
    while cycles > 0:
        n = min(per_move, cycles)
        out.append(sign * n * bl.PIVOT_CYCLE_DEG)
        cycles -= n
    return out


def lap_table(st: CircleState) -> list:
    """One row per COMPLETED lap: {"lap", "clean", "soft": [kinds]}. A lap is clean when nothing spoiled it."""
    return [{"lap": n, "clean": not [s for s in st.soft if s["lap"] == n], "soft": [s["kind"] for s in st.soft if s["lap"] == n]} for n in range(st.lap_now())]


def clean_streak(st: CircleState) -> int:
    """How many completed laps in a row, counted back from the latest, were clean."""
    n = 0
    for row in reversed(lap_table(st)):
        if not row["clean"]:
            break
        n += 1
    return n


def straight_for(last_d) -> float:
    """The straight walk after an arc (inches): CIRCLE_STRAIGHT_IN at the right radius, longer when the last read radius was under CIRCLE_RADIUS_IN (the circle widens), shorter when over it."""
    if last_d is None or CIRCLE_STRAIGHT_GAIN == 0.0:
        return CIRCLE_STRAIGHT_IN
    return max(CIRCLE_STRAIGHT_MIN_IN, min(CIRCLE_STRAIGHT_MAX_IN, CIRCLE_STRAIGHT_IN + CIRCLE_STRAIGHT_GAIN * (CIRCLE_RADIUS_IN - float(last_d))))


def next_circle_action(puck, basket, st: CircleState) -> RAction:
    """The next step of the circling search (pure, like `next_retrieval_action`). One wide ARC at a time round the tub kept beside him (owner, 2026-11-24): face the tub, pivot 90 degrees so it is beside him, then arc CIRCLE_ARC_DEG toward it (the firmware's walking arc curves forward while it turns) and walk CIRCLE_STRAIGHT_IN straight to widen
    the circle. The forward picture after that is the cheap check: the tub should be beside him, out of the picture, so a tub IN the picture means the turn was too tight and he turns away by how far forward it stands (too tight was always the problem, never too wide). Only every CIRCLE_PEEK_EVERY arcs does he peek (turn CIRCLE_PEEK_DEG toward the tub so it stands
    about 30 degrees off his nose, read its distance, turn back corrected by it). 360 degrees of arcs is one lap. A puck in view ends it ("found"); CIRCLE_MAX_LAPS laps end it ("circled_twice"); the tub out of view after a peek or at the start makes him pivot toward its side ("tub_lost" after a full turn); nearer than CIRCLE_MIN_IN he backs off first."""
    if st.streak_target and clean_streak(st) >= st.streak_target:
        return RAction("give_up", 0.0, "passed")
    if st.phase == "arc":
        st.phase = "straight" if straight_for(st.last_d if st.d_arc >= st.arcs else None) > 0 else "glance"
        st.arcs += 1
        st.steps += 1
        st.events.append({"arc": st.arcs, "lap": st.lap_now(), "angle_before": round(st.angle_deg, 1), "asked_deg": CIRCLE_ARC_DEG, "last_d": st.last_d})
        if st.phase == "glance":
            st.cur()["straight_in"] = 0.0
        return RAction("arc", st.side * CIRCLE_ARC_DEG, "circling: wide arc round the tub")
    if st.phase == "straight":
        st.phase = "glance"
        inches = straight_for(st.last_d if st.d_arc >= st.arcs - 1 else None)
        st.cur()["straight_in"] = round(inches, 1)
        return RAction("forward", inches, "circling: walk straight to widen the circle")
    if st.phase == "peek":
        st.phase = "look"
        st.peek_turn = st.peek_deg
        return RAction("pivot", bl._pivot_for(st.side * st.peek_deg), "circling: turn toward the tub to look")
    if puck is not None:
        return RAction("found", 0.0, "puck in view")
    if st.steps >= st.max_steps or st.angle_deg >= 360.0 * st.max_laps:
        return RAction("give_up", 0.0, "circled_twice")
    if st.phase == "glance":
        # the forward picture: no tub is the good case; a tub in it is too tight
        if basket is not None:
            d, b = float(basket.claw_in), float(basket.bearing_deg)
            st.last_d, st.lost_deg = d, 0.0
            st.cur()["glance"] = (round(d, 1), round(b, 1))
            st.d_arc = st.arcs
            if d < CIRCLE_MIN_IN:
                st.steps += 1
                st.note_soft("back_off", d=round(d, 1))
                return RAction("back", min(bl.BACK_STEP_MAX_IN, CIRCLE_RADIUS_IN - d), "circling: too near the tub, back off")
            st.phase = "peek" if st.peek_every > 0 and st.arcs % st.peek_every == 0 else "arc"
            if abs(b) >= CIRCLE_TIGHT_BEARING_DEG and d >= CIRCLE_TIGHT_NEAR_IN:
                turn_away = CIRCLE_SEEN_TURN_DEG                             # in view but well off his nose and not near: a little outward (the owner saw him plow through the tub with no turn at all)
            else:
                turn_away = max(CIRCLE_TIGHT_MIN_TURN_DEG, min(CIRCLE_TIGHT_MAX_TURN_DEG, 90.0 - abs(b)))
            st.note_soft("too_tight", d=round(d, 1), b=round(b, 1))
            st.steps += 1
            return RAction("pivot" if turn_away >= bl.PIVOT_MIN_DEG else "nudge", -st.side * (bl._pivot_for(turn_away) if turn_away >= bl.PIVOT_MIN_DEG else turn_away), "circling: the tub is in view, the turn was too tight: turn away")
        st.phase = "peek" if st.peek_every > 0 and st.arcs % st.peek_every == 0 else "arc"
        return next_circle_action(None, None, st)
    if basket is None:
        if st.phase == "face" and st.lost_deg == 0.0 and st.last_d is not None and st.last_d <= CIRCLE_FIND_FAR_IN and st.find_back < 2:
            st.find_back += 1                                                 # seen a moment ago and not now: it is too near (or off to the side), never walk forward into it
            st.steps += 1
            return RAction("back", CIRCLE_FIND_BACK_IN, "tub lost near the start: back up and look again")
        if st.phase == "face" and st.find_forward < CIRCLE_FIND_FORWARD_MAX and st.lost_deg == 0.0 and (st.last_d is None or st.last_d > CIRCLE_FIND_FAR_IN):
            st.find_forward += 1
            st.steps += 1
            return RAction("forward", CIRCLE_FIND_FORWARD_IN, "tub not in view at the start: walk forward and look again")
        if st.lost_deg >= CIRCLE_LOST_MAX_DEG:
            return RAction("give_up", 0.0, "tub_lost")
        if st.lost_deg == 0.0 and st.phase != "face":
            st.note_soft("tub_lost")
        # a peek that turned far (90 degrees or more) has gone past the tub: look back the way he came first; a short one has not reached it yet: on toward it. Two steps that way, then the other way for the rest (a sweep, never a spin)
        if st.lost_deg == 0.0:
            st.lost_first = -1 if (st.phase == "look" and st.peek_turn >= 90.0) else 1       # decided once, when the tub is first lost
        way = st.lost_first if st.lost_deg < 2 * CIRCLE_LOST_STEP_DEG else -st.lost_first
        if st.phase == "look":
            st.peek_turn += way * CIRCLE_LOST_STEP_DEG
        st.lost_deg += CIRCLE_LOST_STEP_DEG
        st.steps += 1
        return RAction("pivot", st.side * way * CIRCLE_LOST_STEP_DEG, "tub out of view: pivot " + ("toward the side it should be on" if way > 0 else "back the other way"))
    st.lost_deg = 0.0
    d, b = float(basket.claw_in), float(basket.bearing_deg)
    st.last_d = d
    if st.phase == "look":
        st.cur()["peek"] = (round(d, 1), round(b, 1))
        st.d_arc = st.arcs
        if st.peek_turn:                                                      # the tub stood about |b| + the turn made off his beam before the peek: aim the next one to leave it CIRCLE_PEEK_TARGET_DEG off his nose
            st.peek_deg = max(CIRCLE_PEEK_MIN_DEG, min(CIRCLE_PEEK_MAX_DEG, st.side * b + st.peek_turn - CIRCLE_PEEK_TARGET_DEG))
        if not CIRCLE_BAND_IN[0] <= d <= CIRCLE_BAND_IN[1] and d >= CIRCLE_MIN_IN:
            st.note_soft("out_of_band", d=round(d, 1))
    if st.phase == "face" and d < CIRCLE_START_MIN_IN:
        st.steps += 1
        return RAction("back", min(bl.BACK_STEP_MAX_IN, CIRCLE_START_IN - d), "circling: too near the tub to start, back off")
    if d < CIRCLE_MIN_IN and st.phase != "face":
        st.steps += 1
        st.note_soft("back_off", d=round(d, 1))
        return RAction("back", min(bl.BACK_STEP_MAX_IN, CIRCLE_RADIUS_IN - d), "circling: too near the tub, back off")
    if st.phase == "face":
        if abs(b) > CIRCLE_FACE_TOL_DEG:
            st.steps += 1
            return RAction("pivot" if abs(b) >= bl.PIVOT_MIN_DEG else "nudge", bl._pivot_for(b) if abs(b) >= bl.PIVOT_MIN_DEG else b, "circling: face the tub")
        if d > CIRCLE_START_IN + CIRCLE_START_TOL_IN and st.start_walks < CIRCLE_START_WALKS:
            st.start_walks += 1                                               # facing it: walk up to about CIRCLE_START_IN of it, look again (the walk's length is a guess, the next look corrects it)
            st.steps += 1
            return RAction("forward", min(CIRCLE_START_STEP_IN, d - CIRCLE_START_IN), "circling: walk up to the tub")           # short steps: a 5.8 inch walk moved him 9 inches on 2026-11-24
        st.phase = "arc"
        st.steps += 1
        return RAction("pivot", bl._pivot_for(-st.side * CIRCLE_SQUARE_ASK_DEG), "circling: close enough: turn so the tub is beside him")
    # phase "look": he has turned toward the tub; turn back so the tub ends up beside him, more away from it when he is too near and only a little less when too far
    correction = max(-CIRCLE_WIDE_MAX_DEG, min(CIRCLE_CORRECTION_MAX_DEG, CIRCLE_RADIUS_GAIN * (CIRCLE_RADIUS_IN - d)))
    turn_back = CIRCLE_SQUARE_DEG + correction - st.side * b                         # signed: a tub he has turned past (on the other side of his nose) needs the longer turn back
    st.phase = "arc"
    st.steps += 1
    return RAction("pivot" if abs(turn_back) >= bl.PIVOT_MIN_DEG else "nudge", -st.side * (bl._pivot_for(turn_back) if abs(turn_back) >= bl.PIVOT_MIN_DEG else turn_back), "circling: turn back so the tub is beside him")


def circle_report(st: CircleState) -> dict:
    """What a circling run did, for the log and the end-of-run summary: the laps (clean or not and why), the gyro's reading against what was asked, the arc time, the distances read."""
    asked = sum(e.get("asked_deg", 0.0) for e in st.events if e.get("gyro_deg"))
    gyro = sum(e["gyro_deg"] for e in st.events if e.get("gyro_deg"))
    reads = [r[0] for e in st.events for r in (e.get("glance"), e.get("peek")) if r]
    times = [e["arc_s"] for e in st.events if "arc_s" in e]
    return {"laps": lap_table(st), "streak": clean_streak(st), "arcs": len(st.events), "angle_deg": round(st.angle_deg),
            "gyro_over_asked": None if not asked else round(gyro / asked, 2), "arc_s_mean": None if not times else round(sum(times) / len(times), 1),
            "distance_in": None if not reads else {"min": min(reads), "mean": round(sum(reads) / len(reads), 1), "max": max(reads)},
            "soft": list(st.soft), "looks": list(st.looks),
            "look_s": None if not [x["look_s"] for x in st.looks if x["look_s"] is not None] else {"n": len(st.looks), "misses": sum(1 for x in st.looks if not x["ok"]), "max": max(x["look_s"] for x in st.looks if x["look_s"] is not None),
                                                                                                   "mean": round(sum(x["look_s"] for x in st.looks if x["look_s"] is not None) / len([1 for x in st.looks if x["look_s"] is not None]), 2)}}


def circle_report_lines(c: dict) -> list:
    """The circle test's end-of-run summary, one line each: the outcome, the pass check, every lap, the gyro against what was asked, the distances read."""
    r = c["report"]
    lines = [f"CIRCLE TEST {c['outcome']}: {r['arcs']} arcs, {r['angle_deg']} degrees round by the gyro, {len(r['laps'])} lap(s) done, {r['streak']} clean in a row at the end"]
    for lap in r["laps"]:
        lines.append(f"  lap {lap['lap'] + 1}: " + ("clean" if lap["clean"] else "NOT clean: " + ", ".join(lap["soft"])))
    lines.append(f"  looks (picture waits, s): {r.get('look_s')}")
    lines.append(f"  gyro turned {r['gyro_over_asked']} of what was asked per arc; an arc took {r['arc_s_mean']} s on average; tub distances read (in): {r['distance_in']}")
    for e in c["arcs"]:
        lines.append(f"  arc {e['arc']}: asked {e['asked_deg']:.0f}, gyro {e.get('gyro_deg')}, {e.get('arc_s')} s, straight {e.get('straight_in')} in, forward picture {e.get('glance')}, peek {e.get('peek')}")
    return lines


def circle_search(env, say=print, on_step=None, start_side: int = 1, max_laps: float = CIRCLE_MAX_LAPS, peek_every: int = CIRCLE_PEEK_EVERY, deadline: float | None = None, streak_target: int = 0, ignore_puck: bool = False, announce=None) -> dict:
    """Search round the tub for the puck. Returns {"outcome": "found" | "circled_twice" | "tub_lost" | "fell" | "passed" | "time_up" | "camera_stalled" | "battery", "puck", "basket", "steps", "arcs", "report"}; `puck` and `basket` are the last readings when it is found. Uses the environment's quick look and the movers: pivots, a wide `arc`, a back-off.
    The goal calls it with the defaults. The circle test (`--circle-test`) calls the same function with `ignore_puck` (nothing to find), a high `max_laps`, a peek every arc, a `deadline` (time.monotonic) and `streak_target` clean laps in a row; everything else, the rules included, is shared."""
    st = CircleState(side=start_side, max_laps=max_laps, peek_every=peek_every, streak_target=streak_target, max_steps=CIRCLE_MAX_STEPS if streak_target == 0 and not ignore_puck else 100000)
    basket = puck = None
    t_start = time.monotonic()
    misses = 0
    said_basket = False                                                       # "searching for the basket" once per time the tub is lost
    if not ignore_puck:
        _say_searching(announce, "searching for the puck")

    def done(outcome, puck_=None, basket_=None):
        return {"outcome": outcome, "puck": puck_, "basket": basket_, "steps": st.log, "arcs": st.events, "report": circle_report(st)}
    while True:
        if bl.stop_requested():
            return done("stopped", basket_=basket)
        if deadline is not None and time.monotonic() >= deadline:
            return done("time_up", basket_=basket)
        if st.phase == "arc" and hasattr(env, "battery_ok") and not env.battery_ok():
            return done("battery", basket_=basket)
        if st.needs_look:
            try:
                env.circle_note = {"arc": st.arcs, "phase": st.phase, "angle_deg": round(st.angle_deg)}
            except Exception:  # noqa: BLE001
                pass
            try:
                basket, puck = env.look()
            except Fell:
                return done("fell")
            except CameraStalled:
                return done("camera_stalled", basket_=basket)
            st.looks.append({"phase": st.phase, "arc": st.arcs, "look_s": getattr(env, "last_look_s", None), "ok": not getattr(env, "last_quick_failed", False)})
            if getattr(env, "last_quick_failed", False):                    # no picture at all (the camera's USB dropped on 2026-11-24 and the search pivoted blind through 360 degrees): two in a row end it, lying him down
                misses += 1
                if misses >= CAMERA_MISSES_MAX:
                    say("circle: the camera gave no picture twice in a row: stopping")
                    return done("camera_stalled", basket_=basket)
            else:
                misses = 0
            if ignore_puck:
                puck = None
            if basket is not None:
                st.last_d = float(basket.claw_in)
            elif puck is not None and st.last_d is not None and st.last_d < CIRCLE_TAPE_GUARD_IN and _looks_like_tape(puck):
                say("circle: a wide thin 'puck' with the tub out of view this near it is the tub's own tape: ignored")
                puck = None
        act = next_circle_action(puck, basket, st)
        if act.why.startswith("tub out of view") or act.why.startswith("tub not in view") or act.why.startswith("tub lost"):
            if not said_basket:
                said_basket = True
                _say_searching(announce, "searching for the basket")
        elif basket is not None:
            said_basket = False
        st.log.append({"action": act.kind, "value": round(act.value, 1), "why": act.why, "angle_deg": round(st.angle_deg), "puck": None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1)),
                       "basket": None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1))})
        say(f"circle: {act.why}" + (f" ({act.kind} {act.value:.1f}, {st.angle_deg:.0f} degrees round)" if act.kind not in ("found", "give_up") else ""))
        if on_step is not None:
            on_step(st.log)
        if act.kind == "found":
            _say_target(announce)
            return done("found", puck, basket)
        if act.kind == "give_up":
            return done(act.why, basket_=basket)
        if hasattr(env, "ready_to_move"):
            try:
                env.ready_to_move()
            except Fell:
                return done("fell")
        if act.kind != "arc" and hasattr(env.mover, "set_distance"):
            env.mover.set_distance(None if basket is None else float(basket.claw_in))
        t0 = time.monotonic()
        if act.kind == "pivot":
            moves = pivot_chunks(act.value)
        else:
            moves = [act.value]
        failed = False
        for mv in moves:
            if getattr(env.mover, act.kind)(mv) == "fell":
                failed = True
                break
        if failed:
            return done("fell")
        took = round(time.monotonic() - t0, 1)
        if act.kind == "arc":
            gyro = abs(getattr(env.mover, "last_arc_deg", abs(act.value)))
            st.angle_deg += gyro * CIRCLE_ANGLE_SCALE
            ev = st.cur()
            g = getattr(env.mover, "last_arc_gyro_deg", None)
            cmd = getattr(env.mover, "last_arc_s", None)
            ev.update({"counted_deg": round(gyro, 1), "gyro_deg": None if g is None else round(g, 1), "arc_s": took, "cmd_s": cmd, "tail_s": None if cmd is None else round(took - cmd, 1), "t_s": round(time.monotonic() - t_start, 1), "pack_pct": getattr(env, "pack_pct", None)})
        elif act.kind == "forward" and st.events:
            st.cur()["straight_s"] = took


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


def close_align_on() -> bool:
    """G2_PICK_CLOSE_ALIGN=0 puts the pick-up back to the blind last walk and pick (the closed-loop alignment is the default: owner, 2026-11-26)."""
    return os.environ.get("G2_PICK_CLOSE_ALIGN", "1") != "0"


def next_close_action(reading) -> RAction | None:
    """Pure: what to do about a puck read by `puck_close` before the pick-up: None when it sits at the pick-up spot (or cannot be read: the pick-up goes on as it always did), else the correction, the column first (a turn), then the distance."""
    if reading is None or reading.at_spot:
        return None
    clipped = reading.base_row >= CLIPPED_ROW_PX
    if abs(reading.col_err_px) > (CLIPPED_COL_TOL_PX if clipped else puck_close.COL_TOL_PX):
        return RAction("nudge", reading.bearing_err_deg, f"the puck is {reading.col_err_px:+d} px off the pick-up spot sideways: turn onto it")
    if reading.row_err_px < -puck_close.ROW_TOL_PX and CLOSE_FORWARD_IN > 0:
        return RAction("forward", CLOSE_FORWARD_IN, f"the puck sits {-reading.row_err_px} px beyond the pick-up spot: a short step")
    if reading.row_err_px > puck_close.ROW_TOL_PX and not clipped:
        return RAction("back", CLOSE_BACK_IN, f"the puck sits {reading.row_err_px} px nearer than the pick-up spot: a short back-up")
    return None


def close_align(env, st, say=print) -> str:
    """After the last walk and before the pick-up: look, compare the puck with the pick-up spot, correct (up to CLOSE_ALIGN_TRIES times). Returns "aligned", "unread" (no close reading: the pick-up goes on), "tries" (corrected as often as allowed) or "fell". Needs an env with `close_reading()` (the real one; the made-up ones in tests have none and skip this)."""
    if not close_align_on() or not hasattr(env, "close_reading"):
        return "unread"
    for n in range(CLOSE_ALIGN_TRIES + 1):
        try:
            env.look()
        except Fell:
            return "fell"
        reading = env.close_reading()
        if reading is not None and not reading.puck_sized:
            if reading.base_row >= CLIPPED_UNDER_JAW_ROW_PX and reading.height_px >= CLIPPED_MIN_HEIGHT_PX and st.last_seen_in is not None and st.last_seen_in <= CLIPPED_UNDER_JAW_IN:
                say(f"close look: a {reading.width_px} px wide blob at row {reading.base_row}, the puck's last reading {st.last_seen_in:.1f} in: the puck is behind the jaw, picking")
                st.log.append({"action": "close_look", "value": float(n), "why": f"narrow blob at the bottom rows (width {reading.width_px}, base row {reading.base_row}, column {reading.centre_col}) after a last walk: the puck is behind the jaw: pick-up", "puck": None})
                return "aligned"
            say(f"close look: what it read is {reading.width_px} px wide (base row {reading.base_row}, column {reading.centre_col}), not a puck: no puck read at the pick-up spot")
            reading = None                                                                  # clutter or a glint (2026-11-27 run), never a puck to turn by or to call "at the spot"
        act = next_close_action(reading)
        floor = getattr(env, "last_floor_puck", None)
        if act is None and reading is not None and floor is not None and float(floor.claw_in) <= GONE_WITHIN_IN and abs(float(floor.bearing_deg)) > CLOSE_FLOOR_BEARING_DEG:
            act = RAction("nudge", float(floor.bearing_deg), f"the floor finder reads the puck {float(floor.bearing_deg):+.0f} deg off: turn onto it")   # "at the spot" by the close finder, but 22 deg off by the floor finder in the same picture (2026-11-27 run)
        st.log.append({"action": "close_look", "value": float(n), "why": "no close reading" if reading is None else f"base row {reading.base_row}, column {reading.centre_col}, width {reading.width_px}" + (": at the pick-up spot" if act is None else ": " + act.why), "puck": None})
        if reading is None:
            say("close look: no puck read near the claw tip")
            return "unread"
        if act is None:
            say("close look: the puck is at the pick-up spot")
            return "aligned"
        if n >= CLOSE_ALIGN_TRIES:
            say("close look: corrected as often as allowed: the pick-up goes on")
            return "tries"
        say(f"close look: {act.why}")
        st.steps += 1
        if getattr(env.mover, act.kind)(act.value) == "fell":
            return "fell"
    return "tries"


DROP_NEAR_IN = GONE_WITHIN_IN          # a puck seen on the floor this near during the line-up, while he is holding it
DROP_PICTURES, DROP_OF_LAST = 2, 3     # in this many of the last DROP_OF_LAST line-up pictures: it was dropped (2026-11-27 run: the first line-up pivot dropped it, the floor puck read 5.7 to 11 inches in the next pictures and the run lined up empty-handed for 11 minutes). Held, the puck is never read on the floor: the pick-up check relies on that
MAX_DROPS = 2                          # fetches of a dropped puck per attempt; after that the line-up runs unwatched


class PuckDropped(Exception):
    """The line-up's pictures show the puck on the floor again: it is no longer in the claw."""

    def __init__(self, puck):
        super().__init__("puck dropped")
        self.puck = puck


def watch_for_drop(env):
    """The line-up's look, watching for the held puck lying on the floor: it takes the picture as `env.quick_basket` does, and raises `PuckDropped` when the same picture's floor puck (`env.last_floor_puck`, set by the real env; a mock without it never trips) read within DROP_NEAR_IN in DROP_PICTURES of the last DROP_OF_LAST pictures."""
    hist: list = []

    def look():
        basket = env.quick_basket()
        puck = getattr(env, "last_floor_puck", None)
        hist.append(puck if puck is not None and float(puck.claw_in) <= DROP_NEAR_IN else None)
        del hist[:-DROP_OF_LAST]
        if sum(x is not None for x in hist) >= DROP_PICTURES:
            raise PuckDropped(next(x for x in reversed(hist) if x is not None))
        return basket
    return look


def held_check(env) -> str:
    """After the pick-up: "held" when the picture just taken shows a puck-sized blob in the jaw (base row HELD_BASE_ROW_MIN or lower), "not_held" when the puck is seen on the floor after a short back-up, else "held" (nothing seen anywhere: 2026-11-27 run, two misses read as picked up because a puck beside the claw is cropped out of the frame, and one held puck read as a big blob at the bottom centre). "fell" when the back-up ends in a fall."""
    reading = env.close_reading()
    if reading is not None and reading.puck_sized and reading.base_row >= HELD_BASE_ROW_MIN and abs(reading.col_err_px) <= 2 * 10:
        return "held"
    if env.mover.back(HELD_CHECK_BACK_IN) == "fell":
        return "fell"
    try:
        _b, puck = env.look()
    except Fell:
        return "fell"
    return "not_held" if puck is not None and float(puck.claw_in) <= GONE_WITHIN_IN else "held"


def retrieve(env, say=print, on_step=None, first=None, announce=None) -> dict:
    """Search for the puck, walk to it and pick it up. Returns {"outcome": "retrieved" | a give-up reason | "fell", "steps": [...]}."""
    st = RState()
    lost = False                                   # he was scanning for the puck: when it comes back into view he says so
    while True:
        if bl.stop_requested():
            return {"outcome": "stopped", "steps": st.log}
        if first is not None:                      # the first step uses what the look after the throw just saw: no picture, no pause (owner, 2026-11-23)
            (basket, puck), first = first, None
        else:
            try:
                basket, puck = env.look()
            except Fell:
                return {"outcome": "fell", "steps": st.log}
        act = next_retrieval_action(puck, basket, st)
        if act.kind == "scan":
            if not lost:
                _say_searching(announce, "searching for the puck")
            lost = True
        elif lost and puck is not None and act.kind != "give_up":
            lost = False
            _say_target(announce)
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
            ca = close_align(env, st, say)
            if ca == "fell":
                return {"outcome": "fell", "steps": st.log}
            if ca in ("unread", "tries") and close_align_on() and hasattr(env, "close_reading") and st.reapproach < CLOSE_REAPPROACH_MAX:
                st.reapproach += 1
                st.steps += 1
                why = "corrected as often as allowed and the puck is still off the pick-up spot" if ca == "tries" else "no puck read at the pick-up spot"
                st.log.append({"action": "reapproach", "value": CLOSE_REAPPROACH_BACK_IN, "why": f"{why}: back up and look again instead of picking blind", "puck": None})
                say(f"retrieve: {why}: back up and look again instead of picking blind")
                if env.mover.back(CLOSE_REAPPROACH_BACK_IN) == "fell":
                    return {"outcome": "fell", "steps": st.log}
                continue
            got = env.pick()
            st.picks += 1
            if got == "fell":
                return {"outcome": "fell", "steps": st.log}
            try:
                _b, still = env.look()
            except Fell:
                return {"outcome": "fell", "steps": st.log}
            gone = still is None or still.claw_in > GONE_WITHIN_IN
            note = "puck gone from the floor" if gone else "puck still on the floor"
            if gone and close_align_on() and hasattr(env, "close_reading"):
                held = held_check(env)
                if held == "fell":
                    return {"outcome": "fell", "steps": st.log}
                if held == "not_held":
                    gone, note = False, "puck gone from the floor but not in the claw: it lies beside him"
            st.log.append({"action": "picked_check", "value": 0.0, "why": note, "puck": None if still is None else (round(still.claw_in, 1), round(still.bearing_deg, 1))})
            if gone:
                return {"outcome": "retrieved", "steps": st.log}
            if st.picks >= PICK_TRIES:
                return {"outcome": "pick_failed", "steps": st.log}
            continue
        if hasattr(env.mover, "set_distance"):
            env.mover.set_distance(None if puck is None else float(puck.claw_in))     # the turn picks pivot or arc by how far the puck is
        result = getattr(env.mover, {"scan": "scan", "pivot": "pivot", "nudge": "nudge", "forward": "forward", "back": "back"}[act.kind])(act.value)
        if result == "fell":
            return {"outcome": "fell", "steps": st.log}


AGREE_X, AGREE_Y = 0.15, 0.25          # two pictures agree on a puck inside the tub when it sits within this fraction of the tape's width of the same spot (sideways, up and down)


def tub_puck_agrees(a, b) -> bool:
    """Do two quick pictures (basket, floor puck, puck inside) both show a puck inside the tub in the same place, measured against the tub's own tape (so the walk between them does not matter)? One bad frame is not a make (owner approved 2026-11-25)."""
    if a is None or b is None or a[2] is None or b[2] is None or a[0] is None or b[0] is None:
        return False

    def rel(r):
        bk, tp = r[0], r[2]
        w = float(getattr(bk, "width_px", 0) or 0)
        if w <= 0:
            return None
        return (tp.x - (bk.left + bk.right) / 2.0) / w, (tp.y - bk.rim_row) / w
    ra, rb = rel(a), rel(b)
    return ra is not None and rb is not None and abs(ra[0] - rb[0]) <= AGREE_X and abs(ra[1] - rb[1]) <= AGREE_Y


def _say_searching(announce, text: str) -> None:
    """"Searching for the puck" / "searching for the basket" aloud when a search begins (owner, 2026-11-25). Never raises."""
    if announce is not None:
        try:
            announce(text)
        except Exception:  # noqa: BLE001
            pass


def _say_target(announce) -> None:
    """"Target acquired" aloud when he finds the puck (owner, 2026-11-25; the ball goal says it too). Never raises."""
    if announce is not None:
        try:
            announce("target acquired")
        except Exception:  # noqa: BLE001
            pass


def find_tub_ahead(env, say=print, announce=None) -> tuple:
    """The after-throw look did not read the tub: walk forward in short bursts, a quick picture after each, until it is read (owner, 2026-11-25: it is always right in front of him, he may just need to get closer). Returns (reading or None after BLIND_BURSTS, how many bursts it took). Raises Fell if a walk ends in a fall."""
    _say_searching(announce, "searching for the basket")
    for n in range(1, BLIND_BURSTS + 1):
        say(f"no tub in view after the throw: walking forward and looking again ({n} of {BLIND_BURSTS})")
        if env.mover.forward(BLIND_BURST_IN) == "fell":
            raise Fell()
        reading = env.quick_basket()
        if reading is not None:
            return reading, n
    return None, BLIND_BURSTS


def _rest(env, rec: dict) -> None:
    """Lay him down in rest once for this attempt (`rec["rested"]`): every way an attempt can end, other than a fall, ends with him lying, never standing about (owner, 2026-11-24: the legs sag after about 10 s and he fell on the next move). A fake environment without `lie_down` is left alone."""
    if rec.get("rested") or not hasattr(env, "lie_down"):
        return
    env.lie_down()
    rec["rested"] = True


def confirm_throw(env, rec: dict, say=print, persist=lambda state="running": None, first=None, look: str | None = None, announce=None) -> dict:
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
        lu = bl.lineup(walk_look, env.mover, say=say, target_in=bl.CONFIRM_READING_IN, dist_tol=bl.CONFIRM_TOL_IN, align_tol=bl.CONFIRM_ALIGN_TOL_DEG, first=first, announce=announce)
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


def _attempt_once(env, rec: dict, holding: bool, say=print, persist=lambda state="running": None, announce=None) -> tuple[str | None, bool]:
    """ONE attempt: the throw, the look, and after a miss the retrieval and the line-up for the next throw. `rec` is the attempt's record (filled in as it goes). Returns (why it must stop or None to go on, whether he is holding the puck
    for the next throw). The stop reasons are those of `run_sequence`; "made" (a puck seen inside the tub from close up) and the other after-throw codes end a run for the owner's reset. The goal (goals/basket.py) and `run_sequence` both call this."""
    n = rec.get("attempt", 1)
    if not env.battery_ok():
        return "battery", holding
    if bl.stop_requested():
        return "stopped", holding
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
    if code == bo.NO_BASKET and hasattr(env, "confirm_look") and hasattr(env, "quick_basket"):
        try:
            found, bursts = find_tub_ahead(env, say, announce)
        except Fell:
            return "fell", holding
        rec["after"]["tub_found_after_bursts"] = bursts if found is not None else None
        if found is not None:
            basket, code = found, bo.NOT_SEEN                                      # the tub is in view now: look into it as for any throw whose puck was not seen
            say(f"tub in view after {bursts} walk(s) forward: looking into it")
        persist()
    if bl.stop_requested():
        return "stopped", holding
    if puck is not None:
        _say_target(announce)                                                      # the puck seen on the floor right after the throw
    confirm = code == bo.NOT_SEEN                                                  # a puck seen on the floor outside the tub is a certain miss: no confirm, straight to the pick-up (owner, 2026-11-24)
    if confirm and hasattr(env, "confirm_look"):
        # The puck was not seen from about 16 inches: inside the clear tub it is 0 to 5 coloured pixels there. Walk up to about 8 inches, look into it from the attention pose and read the picture (owner, 2026-11-24).
        res = confirm_throw(env, rec, say, persist, first=basket, announce=announce)
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
        c = circle_search(env, say=say, on_step=on_circle, announce=announce)
        rec["circle"] = {"outcome": c["outcome"], "steps": c["steps"]}
        persist()
        if c["outcome"] != "found":
            rec["retrieval"] = {"outcome": "puck_not_found" if c["outcome"] != "fell" else "fell", "steps": []}
            if c["outcome"] != "fell":
                _rest(env, rec)                                                   # two laps without the puck (or the tub lost): the session ends at rest
            return ("fell" if c["outcome"] == "fell" else c["outcome"]), holding
        basket, puck = c["basket"], c["puck"]
    r = retrieve(env, say=say, on_step=on_step, first=(basket, puck), announce=announce)
    rec["retrieval"] = r
    persist()
    if r["outcome"] != "retrieved":
        return r["outcome"], holding
    drops = 0
    while True:
        try:
            lu = bl.lineup(watch_for_drop(env) if drops < MAX_DROPS else env.quick_basket, env.mover, say=say, announce=announce)
            break
        except PuckDropped as e:
            drops += 1
            rec.setdefault("dropped", []).append({"puck": (round(float(e.puck.claw_in), 1), round(float(e.puck.bearing_deg), 1))})
            say("line-up: the puck is on the floor again (dropped): fetching it")
            _say_target(announce)
            r = retrieve(env, say=say, on_step=on_step, first=(None, e.puck), announce=announce)
            rec["retrieval"] = r
            persist()
            if r["outcome"] != "retrieved":
                return r["outcome"], holding
    rec["lineup"] = {"outcome": lu["outcome"], "steps": lu["steps"]}
    persist()
    if lu["outcome"] != "aligned":
        return lu["outcome"], holding
    return None, True


def attempt_once(env, rec: dict, holding: bool, say=print, persist=lambda state="running": None, announce=None) -> tuple[str | None, bool]:
    """ONE attempt (see `_attempt_once`). Whatever stops it, other than a fall, he is laid down in rest before this returns: a retrieval that gave up, a line-up that could not align, a camera that stalled, the battery. Standing idle after the attempt let the legs sag and he fell on the next move
    (2026-11-24). Returns (why it must stop or None to go on, whether he is holding the puck)."""
    why, holding = _attempt_once(env, rec, holding, say, persist, announce)
    if why and why != "fell":
        _rest(env, rec)
    return why, holding


def run_sequence(env, max_attempts: int = MAX_ATTEMPTS, say=print, save=None) -> dict:
    """The attempts. Returns {"outcome": ..., "attempts": [...]}; the outcome says why it stopped: "made" (stop for the owner's reset), "max_attempts", "fell", "battery", "throw_failed", "circled_twice", "tub_lost", "no_basket",
    "basket_not_found", "could_not_align", "puck_not_found", "could_not_reach_puck", "pick_failed" (older journal rows also carry "too_near_the_basket", which no longer ends a run)."""
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
        self.quick_hist: list = []                                       # the last few quick pictures' readings: the confirm needs two that agree
        try:
            looker._cam._timeout_s = QUICK_PICTURE_TIMEOUT_S              # a stalled camera ends a look in a few seconds, not eight a request
        except Exception:  # noqa: BLE001
            pass

    def _premeter(self, cam) -> None:
        """Meter the light in the camera's own background thread while the claw rises and pans, so the look's pictures do not meter (up to four throwaway grabs, each a chance to stall) while he stands waiting for them. Never raises."""
        try:
            fn = getattr(cam, "premeter", None)
            if callable(fn):
                fn()
        except Exception:  # noqa: BLE001
            pass

    def _picture_wait(self, seconds: float) -> None:
        """How long the next picture request waits for the camera: AFTER_PICTURE_TIMEOUT_S for the claw look (its right-hand picture needs the longer wait), QUICK_PICTURE_TIMEOUT_S for the quick pictures between moves."""
        try:
            self.looker._cam._timeout_s = seconds
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
        self._picture_wait(AFTER_PICTURE_TIMEOUT_S)
        cam, seen = self._camera(), {}
        self._premeter(cam)
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
        self._picture_wait(AFTER_PICTURE_TIMEOUT_S)
        cam, got = self._camera(), {}
        self._premeter(cam)
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

    def stand_up_warm(self) -> str:
        """The eased stand-up from rest while the camera takes a throwaway picture on its own thread: the first picture after a quiet spell can take 5 s, and he stood still through it (2026-11-24: the legs sagged before the first move). "ok" or "fell"."""
        import threading

        def warm():
            try:
                self._camera().look()
            except Exception:  # noqa: BLE001
                pass
        t = threading.Thread(target=warm, daemon=True)
        t.start()
        res = self.robot.stand_up_from_rest()
        t.join(timeout=8.0)
        return res

    def idle_stand_s(self) -> float | None:
        """How long he has stood with no leg move (since the last move or stand-up ended), or None when that is not known or he is not standing."""
        moved = getattr(self.robot, "_moved_at", None)
        if moved is None or getattr(self.robot, "posture", "stand") not in ("stand", "unknown"):
            return None
        try:
            return float(self.robot._clock() - moved)
        except Exception:  # noqa: BLE001
            return None

    def _rest_if_idle(self) -> bool:
        """No picture came and he has stood STAND_IDLE_REST_S or more with no leg move: lie him down now rather than wait for another try (a stall left him standing 12 to 13 s and the legs sagged). True when he was laid down; the next look or move stands him up from rest."""
        idle = self.idle_stand_s()
        if idle is None or idle < STAND_IDLE_REST_S:
            return False
        self.idle_rests = getattr(self, "idle_rests", 0) + 1
        self.lie_down()
        return True

    def ready_to_move(self) -> None:
        """Stand him up if he is lying (after an idle rest), before any move: the moves send nothing of their own to stand him."""
        self._ready_to_move()

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
        self._picture_wait(QUICK_PICTURE_TIMEOUT_S)
        cam = self._camera()
        t_look = time.monotonic()
        jpeg = cam.look()                                                # no forced re-metering: the warm-up metered the light
        self.last_look_s = round(time.monotonic() - t_look, 2)
        self.last_quick_failed = not jpeg
        if not jpeg:
            self.last_quick = None
            self._rest_if_idle()
            return None, None
        basket = bf.find_basket(jpeg)
        puck = pf.find_puck(jpeg, basket, by=by)
        tub_puck = pf.find_puck_in_tub(jpeg, basket)
        try:
            self._last_close = puck_close.find_close(jpeg)             # the puck at the pick-up spot (the floor finder above cannot read one this near)
        except Exception:  # noqa: BLE001
            self._last_close = None
        self.last_floor_puck = puck                                      # the floor finder's reading in this picture (the close alignment and the line-up's drop watch cross-check against it)
        self.last_quick = (basket, puck, tub_puck)                       # what the confirm step reads when this was its picture (`quick_confirm`)
        self.quick_hist = (getattr(self, "quick_hist", []) + [self.last_quick])[-3:]
        n = len(self.quick_log) + 1
        d = os.path.join(os.path.expanduser(LOG_DIR), "quick", self.run_stamp)
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"q{n:02d}.jpg"), "wb") as f:
                f.write(jpeg)
        except OSError:
            pass
        self.last_walkup = None if basket is None else (round(basket.claw_in, 1), round(basket.width_px))
        save_picture(getattr(self, "run_stamp", "run"), getattr(self, "attempt", 0), f"quick{n:02d}", jpeg, basket, puck, tub_puck, {"by": by, "look_s": self.last_look_s, "circle": getattr(self, "circle_note", None)})
        self.quick_log.append({"n": n, "time": time.strftime("%H:%M:%S"),
                               "basket": None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1), basket.width_px),
                               "puck": None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1), puck.width_px, round(puck.y))})
        return basket, puck

    @property
    def quick_count(self) -> int:
        return len(self.quick_log)

    def quick_confirm(self):
        """The confirm step's reading from the last quick picture (claw down, taken at the end of the walk-up): (tub, puck on the floor, puck inside the tub), read when the picture was taken, so nothing waits."""
        cur = self.last_quick if self.last_quick is not None else (None, None, None)
        if cur[2] is None:
            return cur
        hist = getattr(self, "quick_hist", [])
        if len(hist) >= 2 and tub_puck_agrees(hist[-2], cur):            # the walk-up's last two pictures both show it in the same place
            return cur
        self._quick("width")                                              # one more picture: a puck in the tub stays put, a glint or a stale frame does not
        again = self.last_quick
        if again is not None and tub_puck_agrees(cur, again):
            return again
        return (cur[0], cur[1], None)                                     # not confirmed: nothing inside

    def look(self):
        """The retrieval's look: a quick claw-down picture, as the ball goal takes while it walks up (the puck's distance from its row). A puck read only by the relaxed second pass (a small or pale one, `PuckReading.relaxed`) is trusted when a second picture puts it in the same place: a speck of the room's clutter does not stay put in the same spot relative to G2 as he moves.
        `G2_PUCK_RELAXED_CONFIRM=0` takes the first picture as it is."""
        from ..vision import puck_finder as pf
        basket, puck = self._quick("width")
        if puck is None or not getattr(puck, "relaxed", False) or os.environ.get("G2_PUCK_RELAXED_CONFIRM", "1") == "0":
            return basket, puck
        basket2, puck2 = self._quick("width")
        if pf.readings_agree(puck, puck2):
            return basket2, puck2
        return basket2, None                                              # not confirmed: not seen

    def close_reading(self):
        """The last quick picture's puck against the pick-up spot (`puck_close.CloseReading`), or None."""
        return getattr(self, "_last_close", None)

    def quick_basket(self):
        """The line-up's look: a quick claw-down picture, the basket's reading or None. The same picture's floor puck is kept in `last_floor_puck` (the line-up watches it for a dropped puck)."""
        basket, puck = self._quick("width")
        self.last_floor_puck = puck
        return basket

    def drop(self):
        """Let go of the puck: raise the arm, open then close the claw, lower the arm (behavior/drop.py, the move every way in shares). "ok" or "fell"."""
        from . import ball_chase as bc
        from .drop import drop_puck

        def read_arm():
            joints = bc.read_joints(self.link)
            return None if not joints or len(joints) < 3 else list(joints[:3])
        self.last_drop: dict = {}
        return drop_puck(self.robot, read_arm=read_arm, info=self.last_drop)

    def claw_to(self, lift: float) -> str:
        """The arm to `lift` (0 is down, centred): "ok" or "fell". The claw look's own move, at its own speed, watching the IMU."""
        return self.robot.claw_pose(0.0, float(lift))

    def tilt_now(self):
        """The body's (pitch, roll) in degrees from a fresh IMU read, or None."""
        try:
            t = self.robot._tilt(0.3)
        except Exception:  # noqa: BLE001
            return None
        return None if t is None else (round(float(t[0]), 1), round(float(t[1]), 1))

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
    ap.add_argument("--circle-test", action="store_true", help="the circle test: stand up from rest and circle the tub over and over (no puck, nothing thrown; the tub about 16 inches out, four feet of clear floor round it) until --minutes run out or --laps clean laps follow one another, then lie down; logs every arc and picture, prints a lap table")
    ap.add_argument("--minutes", type=float, default=CIRCLE_TEST_MINUTES, help="with --circle-test: the time cap")
    ap.add_argument("--peek-every", type=int, default=CIRCLE_PEEK_EVERY, help="with --circle-test: a peek every this many arcs (default CIRCLE_PEEK_EVERY, the goal's own: owner, 2026-11-24; 1 = every arc, for more data; on the simulated floor every arc held the 12 to 22 inch band worse than every third)")
    ap.add_argument("--no-peek", action="store_true", help="with --circle-test: no peeks at all (the same as --peek-every 0): the tub not in the forward picture means he is still circling it (owner, 2026-11-25)")
    ap.add_argument("--laps", type=int, default=CIRCLE_TEST_LAPS_IN_A_ROW, help="with --circle-test: clean laps in a row that pass the test")
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
        if a.circle_test:
            env.attempt = 0
            if env.stand_up_warm() == "fell":
                raise Fell()
            c = circle_search(env, say=print, max_laps=1000, peek_every=0 if a.no_peek else a.peek_every, deadline=time.monotonic() + 60.0 * a.minutes, streak_target=a.laps, ignore_puck=True)
            ok2, pct_end, _v = battery.motion_gate(link)
            env.lie_down() if c["outcome"] != "fell" else None
            for line in circle_report_lines(c):
                print(line)
            circle_log = write_log({"outcome": c["outcome"], "attempts": []}, {"circle_test": {"minutes": a.minutes, "laps": a.laps, "outcome": c["outcome"], "report": c["report"], "arcs": c["arcs"], "steps": c["steps"]}, "pack_pct_start": pct, "pack_pct_end": pct_end}, path=os.path.join(os.path.expanduser(LOG_DIR), time.strftime("%Y%m%d_%H%M%S") + "_circle_test.json"))
            print("logged", circle_log, "; pictures kept in", os.path.join(os.path.expanduser(LOG_DIR), "pictures", env.run_stamp))
            return
        if a.confirm_only or a.circle_only:
            env.attempt = 0
            if env.stand_up_warm() == "fell":
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
