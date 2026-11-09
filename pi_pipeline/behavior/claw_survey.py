"""The claw look as THE way G2 looks (user, 2026-11-06: "the new look should always use the claw look"), replacing the bow, the sit and the firmware `check` pose that the survey stops,
the namings and the milestone pictures used.

With the arm fitted a look is: the attention pose (`kcalib`, the legs straight), the claw raised straight up, the camera swung to G2's left (picture), to his right (picture), back to the
centre (the picture that counts), the claw lowered, then he stands up (`kup`, eased). It is the same move as `ball_chase.claw_scan` made from the attention pose, without the ball finding.
The survey plan (`behavior/survey.py`) holds the timing: the pose, one "claw" step that runs `run_claw_look` here in a worker thread (the behaviour loop keeps ticking), the stand.

Without the arm (`G2_ATTACHMENT` head or none) the plan stays what it was: look up, look down, stand. `G2_SURVEY_CLAW=0` forces the old looks, `=1` forces the claw one.
"""
from __future__ import annotations

import logging
import math
import os
import time

log = logging.getLogger("g2.claw_survey")

SETTLE_S = 1.5            # after each swing, before the picture: the camera's frames are about 1 s old (CLAUDE.md), so a shorter wait shows the pose before the move
RAISE_FIRST = True        # from the attention pose the claw sits between the front legs and cannot pan there: raise it straight up first (ball_chase.CLAW_RAISE_FIRST)


def wanted() -> bool:
    """Whether looks use the claw: the arm is fitted (`G2_SURVEY_CLAW=1` / `0` forces it)."""
    v = os.environ.get("G2_SURVEY_CLAW", "").strip().lower()
    if v in ("1", "on", "true", "yes"):
        return True
    if v in ("0", "off", "false", "no"):
        return False
    try:
        from ..attachments import current
        return current() == "arm"
    except Exception:  # noqa: BLE001
        return False


class _Halt(Exception):
    """`stopped()` went true in the middle of an arm move (a fall): no more moves are sent."""


def _smooth(link, a: tuple[float, float], b: tuple[float, float], sleep, stopped=None) -> None:
    """Move the arm (pan joint 0, lift joint 1) from a to b at CLAW_DEG_S, eased: the same stepping as `SerialRobot.claw_pose`."""
    from .ball_chase import CLAW_DEG_S, CLAW_STEPS_PER_S
    span = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
    steps = max(1, int(math.ceil(span / CLAW_DEG_S * CLAW_STEPS_PER_S)))
    sent_p = sent_l = None
    for i in range(1, steps + 1):
        u = i / steps
        k = u * u * (3 - 2 * u)
        pi_, li_ = int(round(a[0] + (b[0] - a[0]) * k)), int(round(a[1] + (b[1] - a[1]) * k))
        parts = ([f"0 {pi_}"] if pi_ != sent_p else []) + ([f"1 {li_}"] if li_ != sent_l else [])          # only the joint that changed (see ball_chase.claw_pose)
        if parts:
            link.send("i" + " ".join(parts), read_reply=False, settle=0.0)
            sent_p, sent_l = pi_, li_
        sleep(1.0 / CLAW_STEPS_PER_S)
        if stopped is not None and i % 10 == 0 and stopped():
            raise _Halt()


def look_seconds() -> float:
    """About how long `run_claw_look` takes (the survey plan waits this long before standing up): the arm moves plus three settles."""
    from .ball_chase import CLAW_DEG_S, CLAW_LIFT_DEG, CLAW_PAN_DEG
    moves = CLAW_LIFT_DEG + CLAW_PAN_DEG + 2 * CLAW_PAN_DEG + CLAW_PAN_DEG + CLAW_LIFT_DEG       # degrees swept: up, left, right, centre, down
    return moves / CLAW_DEG_S + 3 * SETTLE_S + 1.0


def run_claw_look(link, snapshot, kind: str, *, sleep=time.sleep, stopped=lambda: False) -> str:
    """The look. `snapshot(kind)` takes one picture (None = no camera: the arm still moves). Throwaway pictures are `look_left` / `look_right`; the centre one is `kind`.
    Returns "ok", "stopped" (stopped() went true between moves) or "error"; the arm always ends lowered. Never raises."""
    from .ball_chase import CLAW_LIFT_DEG, CLAW_PAN_DEG, CLAW_PAN_SIGN
    left = CLAW_PAN_DEG if CLAW_PAN_SIGN == "left" else -CLAW_PAN_DEG              # the pan that points the camera to G2's left
    here = (0.0, 0.0)
    state, halted = "ok", False
    try:
        link.send("gP", read_reply=False, settle=0.0)
        if RAISE_FIRST:
            _smooth(link, here, (0.0, CLAW_LIFT_DEG), sleep, stopped)
            here = (0.0, CLAW_LIFT_DEG)
        for pan, label in ((left, "look_left"), (-left, "look_right"), (0.0, kind)):
            if stopped():
                state = "stopped"
                break
            _smooth(link, here, (pan, CLAW_LIFT_DEG), sleep, stopped)
            here = (pan, CLAW_LIFT_DEG)
            sleep(SETTLE_S)
            if snapshot is not None:
                snapshot(label)
    except _Halt:
        state, halted = "stopped", True
    except Exception:  # noqa: BLE001
        log.exception("the claw look failed")
        state = "error"
    finally:
        try:
            if not halted:                                                            # (halted mid-move = a fall: nothing more is sent to the arm)
                _smooth(link, here, (0.0, 0.0), sleep)                               # arm down and centred whatever happened
            link.send("gp", read_reply=False, settle=0.0)
        except Exception:  # noqa: BLE001
            log.exception("could not lower the claw")
    return state
