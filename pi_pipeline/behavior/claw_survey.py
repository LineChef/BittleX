"""The claw look as THE way G2 looks, in every mode (owner, 2026-11-13: "use the claw look from the ball chase, that is the one that doesn't fall"; "any change we make to G2 in any mode should apply to all modes").

There is ONE claw look: `ball_chase.claw_look_sequence`, the move the ball chase makes. The exploration (the survey stops), the voice loop (a picture asked for, a naming) and the test drill call it through
`run_claw_look` here; nothing builds its own. It is the whole move from wherever he stands: he stands first, goes into the attention pose (settled), the claw is raised straight up, the camera swings to his
left (picture), to his right (picture), back to the centre (the picture that counts), the claw is lowered, and he stands up (a normal stand-up: out of the attention pose it lies him down in rest first,
`STAND_ATT_VIA_REST`). The callers do not put him in the attention pose and do not stand him up. The numbers are in `ball_chase.py` (CLAW_*) and `motion_feel.py`; changing them changes every mode.

Without the arm (`G2_ATTACHMENT` head or none) the survey plan stays what it was: look up, look down, stand. `G2_SURVEY_CLAW=0` forces the old looks, `=1` forces the claw one.
"""
from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("g2.claw_survey")


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


def look_seconds() -> float:
    """About how long `run_claw_look` takes, all of it (the survey plan schedules by it): stand first, the attention pose settled, the arm moves, three settles, the lowering and the stand-up."""
    from . import ball_chase as bc
    sweep = bc.CLAW_LIFT_DEG + bc.CLAW_PAN_DEG + 2 * bc.CLAW_PAN_DEG + bc.CLAW_PAN_DEG + bc.CLAW_LIFT_DEG       # degrees swept: up, left, right, centre, down
    return bc.SIT_STAND_FIRST_S + bc.CLAW_POSE_S + sweep / bc.CLAW_DEG_S + 3 * bc.CLAW_SETTLE_S + 6.0              # (the last 6 s: lying down in rest and the stand-up from rest)


def run_claw_look(link, snapshot, kind: str, *, sleep=time.sleep, stopped=lambda: False, discard=None, miss_skips: bool = False, robot=None) -> str:
    """THE claw look (see the module note), from standing: the pictures are `look_left`, `look_right` and `kind` (the centre one, the one that counts). `snapshot(label)` takes one picture (None = no camera: the
    arm still moves); `discard()` throws away one stale camera frame before each picture (the module answers with the picture of the PREVIOUS request); `miss_skips` skips the other side picture after the
    camera missed one (it would wait for the camera again); `stopped()` ends it between moves; `robot` is the chase robot to run it on (default: one on `link`). G2 is standing when it returns.
    Returns "ok", "stopped" (stopped, or he fell: the fall guard handles the fall) or "error". Never raises."""
    from . import ball_chase as bc
    left = bc.CLAW_PAN_DEG if bc.CLAW_PAN_SIGN == "left" else -bc.CLAW_PAN_DEG               # the pan that points the camera to G2's left
    labels = {left: "look_left", -left: "look_right", 0.0: kind}
    missed = [False]

    def per_pan(pan) -> bool:
        label = labels.get(pan, kind)
        if label != kind and missed[0]:
            log.warning("the claw look had no picture from the camera: skipping the %s picture", label)
            return False
        if discard is not None:
            discard()                                                                         # ask once and drop it, as the chase's look does (ball_chase._SnapshotCamera.look)
        if snapshot is not None:
            got = snapshot(label)
            if miss_skips and got is None and label != kind:
                missed[0] = True
        return False
    try:
        robot = robot or bc.SerialRobot(link, sleep=sleep)
        state = bc.claw_look_sequence(robot, per_pan, pans=[left, -left, 0.0], from_sit=True, raise_first=True, sleep=sleep, stopped=stopped)
    except Exception:  # noqa: BLE001
        log.exception("the claw look failed")
        return "error"
    return "ok" if state == "ok" else "stopped"
