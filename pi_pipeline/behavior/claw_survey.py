"""The claw look as THE way G2 looks (user, 2026-11-06: "the new look should always use the claw look"), replacing the bow, the sit and the firmware `check` pose that the survey stops,
the namings and the milestone pictures used.

With the arm fitted a look is: the attention pose (`kcalib`, the legs straight), the claw raised straight up, the camera swung to G2's left (picture), to his right (picture), back to the
centre (the picture that counts), then he lies down in the rest position (the claw goes down with the legs, in one motion), then he stands up from rest (`kup`, eased; owner, 2026-11-12: the stand-up
straight out of the attention pose tipped him over backwards after a look). It is the same move as `ball_chase.claw_scan` made from the attention pose, without the ball finding.
The survey plan (`behavior/survey.py`) holds the timing: the pose, one "claw" step that runs `run_claw_look` here in a worker thread (the behaviour loop keeps ticking), the stand.

Without the arm (`G2_ATTACHMENT` head or none) the plan stays what it was: look up, look down, stand. `G2_SURVEY_CLAW=0` forces the old looks, `=1` forces the claw one.
"""
from __future__ import annotations

import logging
import math
import os
import time

log = logging.getLogger("g2.claw_survey")

SETTLE_S = 0.8            # after each swing, before the picture: THE chase's CLAW_SETTLE_S (one claw look in every mode, owner 2026-11-10); the old frame is dropped by `discard` below, not by waiting longer
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


KEEPALIVE_S = float(os.environ.get("G2_ATT_KEEPALIVE_S", "4"))     # while he holds the attention pose the leg angles are sent again this often (0 = never): the servos' own overload cutoff lets a leg go after a while at the same target, and a 30 s hold with the angles re-sent did not sag (2026-11-02)
REST_WAIT_S = 3.5         # after the look the rest command is sent and the board is given this long to report the rest pose before the stand-up reads it
LATE_S = float(os.environ.get("G2_CLAW_LATE_S", "4"))              # a look still running this long past its planned time skips what is left (a slow camera) and lowers the claw: less time in the attention pose


class _KeepAlive:
    """Sends the attention pose's leg angles again every `KEEPALIVE_S` while the look runs, only while the board is in the attention pose (the last motion command was `kcalib`)."""

    def __init__(self, link, clock=None):
        self.link, self._clock = link, clock or (lambda: time.monotonic())
        self._last, self.sent = self._clock(), 0

    def tick(self) -> None:
        if KEEPALIVE_S <= 0 or self._clock() - self._last < KEEPALIVE_S:
            return
        self._last = self._clock()
        try:
            if (getattr(self.link, "last_motion_command", "") or "").strip() != "kcalib":
                return
            from ..gait import standup
            self.link.send(standup.move_cmd(list(standup.ATTENTION_URDF_DEG)), read_reply=False, settle=0.0)
            self.sent += 1
        except Exception:  # noqa: BLE001 -- a keep-alive never stops a look
            log.debug("attention keep-alive failed", exc_info=True)


class _Halt(Exception):
    """`stopped()` went true in the middle of an arm move (a fall): no more moves are sent."""


def _smooth(link, a: tuple[float, float], b: tuple[float, float], sleep, stopped=None, keep=None) -> None:
    """Move the arm (pan joint 0, lift joint 1) from a to b at CLAW_DEG_S, eased: the same stepping as `SerialRobot.claw_pose`."""
    from .ball_chase import CLAW_STEPS_PER_S, claw_path
    sent_p = sent_l = None
    for i, (pi_, li_) in enumerate(claw_path(a, b), 1):
        parts = ([f"0 {pi_}"] if pi_ != sent_p else []) + ([f"1 {li_}"] if li_ != sent_l else [])          # only the joint that changed (see ball_chase.claw_pose)
        if parts:
            link.send("i" + " ".join(parts), read_reply=False, settle=0.0)
            sent_p, sent_l = pi_, li_
        sleep(1.0 / CLAW_STEPS_PER_S)
        if keep is not None:
            keep.tick()
        if stopped is not None and i % 10 == 0 and stopped():
            raise _Halt()
    try:                                                                       # the last position is sent again by itself: a command the board missed while it was busy left the claw down for the whole look (owner, 2026-11-12)
        for _ in range(2):
            link.send(f"i0 {int(round(b[0]))} 1 {int(round(b[1]))}", read_reply=False, settle=0.0)
            sleep(0.1)
    except _Halt:
        raise
    except Exception:  # noqa: BLE001
        pass


def _lie_down(link, sleep) -> bool:
    """The look's last move: the rest position, the claw coming down WITH the legs in one eased K skill (the firmware `krest` snapped the claw down at the end, 2026-11-12). Where the link cannot play that
    skill the firmware `krest` is sent and the board is given a moment to report rest. True when the move ran."""
    from .ball_chase import CLAW_LIFT_DEG, classify_pose, read_joints
    fn = getattr(link, "lie_down_eased", None)
    if callable(fn):
        try:
            if fn(CLAW_LIFT_DEG):
                return True
        except Exception:  # noqa: BLE001
            log.debug("eased lie-down raised", exc_info=True)
    link.send("krest", read_reply=False, settle=0.0)
    sleep(0.8)
    for _ in range(max(1, int(REST_WAIT_S / 0.4))):
        try:
            j = read_joints(link, timeout_s=0.5)
            if j and classify_pose(j) == "rest":
                return True
            if not j:                                                                # the board does not answer: no polling, the stand-up trusts the rest command that was just sent
                sleep(1.0)
                return False
        except Exception:  # noqa: BLE001
            return False
        sleep(0.2)
    return False


def look_seconds() -> float:
    """About how long `run_claw_look` takes (the survey plan waits this long before standing up): the arm moves plus three settles."""
    from .ball_chase import CLAW_DEG_S, CLAW_LIFT_DEG, CLAW_PAN_DEG
    moves = CLAW_LIFT_DEG + CLAW_PAN_DEG + 2 * CLAW_PAN_DEG + CLAW_PAN_DEG + CLAW_LIFT_DEG       # degrees swept: up, left, right, centre, down
    return moves / CLAW_DEG_S + 3 * SETTLE_S + 1.0


def run_claw_look(link, snapshot, kind: str, *, sleep=time.sleep, stopped=lambda: False, discard=None, miss_skips: bool = False, end_in_rest: bool = True) -> str:
    """The look. `snapshot(kind)` takes one picture (None = no camera: the arm still moves). Throwaway pictures are `look_left` / `look_right`; the centre one is `kind`.
    `discard()` throws away one stale camera frame before each picture (the voice loop passes the camera's `discard_one`; the exploration's picture saver already takes throwaway frames). Returns "ok", "stopped" (stopped() went true between moves) or "error". A look that ran to the end (`end_in_rest`) finishes by lying him down in the rest position, which lowers the claw with the legs; one that
    stopped or failed lowers the claw and stays in the attention pose. The caller stands him up after. Never raises."""
    from .ball_chase import CLAW_LIFT_DEG, CLAW_PAN_DEG, CLAW_PAN_SIGN
    left = CLAW_PAN_DEG if CLAW_PAN_SIGN == "left" else -CLAW_PAN_DEG              # the pan that points the camera to G2's left
    here = (0.0, 0.0)
    state, halted = "ok", False
    keep, t0, missed = _KeepAlive(link), time.monotonic(), False
    budget = look_seconds() + LATE_S
    was_on = bool(getattr(link, "imu_print_on", False))
    try:
        link.send("gP", read_reply=False, settle=0.0)
        if RAISE_FIRST:
            _smooth(link, here, (0.0, CLAW_LIFT_DEG), sleep, stopped, keep)
            here = (0.0, CLAW_LIFT_DEG)
        for pan, label in ((left, "look_left"), (-left, "look_right"), (0.0, kind)):
            if stopped():
                state = "stopped"
                break
            if label != kind and (missed or time.monotonic() - t0 > budget):                       # over time (a slow camera): the throwaway pictures are skipped, the one that counts is still taken
                log.warning("the claw look %s: skipping the %s picture", "had no picture from the camera" if missed else f"is {time.monotonic() - t0 - look_seconds():.0f} s over its plan", label)
                continue
            _smooth(link, here, (pan, CLAW_LIFT_DEG), sleep, stopped, keep)
            here = (pan, CLAW_LIFT_DEG)
            sleep(SETTLE_S)
            keep.tick()
            if discard is not None:
                discard()                                                             # the module answers with the picture of the PREVIOUS request: ask once and drop it, as the chase's look does (ball_chase._SnapshotCamera.look)
            if snapshot is not None:
                got = snapshot(label)
                if miss_skips and got is None and label != kind:          # the camera did not answer (the picture saver returns None): the other side picture would wait 6 s again, so it is skipped (2026-11-12)
                    missed = True
                keep.tick()
    except _Halt:
        state, halted = "stopped", True
    except Exception:  # noqa: BLE001
        log.exception("the claw look failed")
        state = "error"
    finally:
        try:
            if not halted and state == "ok" and end_in_rest:
                _lie_down(link, sleep)                                               # one motion: the rest pose takes the claw down with the legs (owner, 2026-11-12)
            elif not halted:                                                          # (halted mid-move = a fall: nothing more is sent to the arm)
                _smooth(link, here, (0.0, 0.0), sleep, None, keep)                   # arm down and centred whatever happened
                from .ball_chase import ensure_claw_centered
                ensure_claw_centered(link, sleep)                                    # confirmed with the board, the same as the chase's claw look
            if not was_on:                                                            # the print stays on where it was on before the look (a guard reads it)
                link.send("gp", read_reply=False, settle=0.0)
        except Exception:  # noqa: BLE001
            log.exception("could not lower the claw")
    return state
