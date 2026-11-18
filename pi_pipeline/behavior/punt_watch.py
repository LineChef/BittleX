"""Watch the ball after a punt (2026-11-15, the owner's design): after the punch G2 goes to the attention pose, follows the rolling ball with the claw until it stops, takes a picture to fix where it
ended, and either has the target (the chase goes on from there) or, if he lost it, turns toward the side it was last seen on and does the normal claw look.

The pieces are the live follow's (behavior/live_follow.py): the camera's continuous picture stream, the claw steered from where it pointed when each picture was taken, and `follow_loop`. This module adds
  * a `StopDetector`: the ball is STOPPED when its WORLD bearing (the claw's direction plus the ball's offset in the picture) and its size have stayed put over `stable_n` pictures;
  * `watch_after_punt`: the stream starts at once (the camera rides the pan base, so it sees the ball while G2 is still moving into the attention pose, and those first pictures are kept for the
    last-seen side), then the attention pose, the claw up, the follow, the stop, the still, and a `WatchResult`:
      found: the ball's reading with its bearing turned into G2's own direction (`claw_pan_body`), ready for the chase as its first reading ("target acquired");
      not found: the side it was last seen on (+1 right, -1 left, 0 unknown) so the caller can turn that way and do the normal claw look.
It never walks. A fall, a sag, or the stop file ends it; the caller owns what comes after.
"""
from __future__ import annotations

import dataclasses
import logging
import time
from collections import deque
from dataclasses import dataclass

from . import live_follow as lf
from .active_look import StopDetector, StopLostConfig, StopOrLostJudge, frame_log, run_active_look  # noqa: F401  (StopDetector and frame_log are re-exported: they lived here first)

log = logging.getLogger("g2.punt_watch")


@dataclass
class WatchConfig(StopLostConfig):
    """The ball's follow: the shared stop-or-lost rule's numbers (behavior/active_look.py) plus the ball's own."""
    lost_turn_deg: float = 40.0        # the turn the caller makes toward the last-seen side (the goal now turns by the last bearing)
    jump_deg: float = 30.0             # a sighting this far from where the tracking filter expects the ball, soon after the last one, must be seen twice before the claw follows it
    lead_s: float = 0.9                # the claw aims this far ahead of the rolling ball (its bearing speed times this); 0 = off. (owner-approved 2026-11-17, set 2026-11-18: the follow calibration measured 0.8 to 1.0 s from a claw command to the picture it shows; it was 0.5)
    coast_s: float = 1.5               # with no sighting in a picture, the claw keeps following the filter's prediction for this long after the last sighting; 0 = off. (it was 1.0: with a 0.8 to 1.0 s delay a picture or two with no ball is normal)


@dataclass
class WatchResult:
    ended: str = "error"               # "stopped" (the ball stopped), "timeout" (still rolling at the limit), "lost", "fell", "sag", "stopped_by_user", "no_board", "error"
    found: bool = False
    reading: object | None = None      # a BallReading with G2's own bearing, when found
    last_side: int = 0                 # +1 right, -1 left, 0 unknown: where it was last seen
    last_bearing: float | None = None
    seconds: float = 0.0
    pictures: int = 0
    moves: int = 0
    rows: list | None = None           # the stream's per-frame log (time, detections, bad frames), for the report
    move_log: list | None = None
    bad_frames: int = 0
    got_it: bool = False               # "Got it." was already said for this punt (the goal's scorer then does not say it again)
    source: str = ""                  # where the reading came from: "still" (the picture after the stop) or "stream" (the stream's own last sightings, when the still missed)
    stream_reading: object | None = None   # what the stream's last sightings said, for the log
    still_diag: dict | None = None     # when the still found nothing: the biggest green blob in it (numbers only)
    sightings: int = 0
    frames: list | None = None         # the stream's per-picture log, compact, for the journal (numbers only)


STREAM_WINDOW_S = 5.0              # the stream's sightings this recent at the end of the follow are the ball's last known place
STILL_RETRIES = 3                  # more pictures from where the claw stands, one after the other, before the ball counts as lost
STILL_RETRY_WAIT_S = 0.6
STREAM_MIN_N = 2                   # ... when there are at least this many of them (a single sighting can be a false one)


def stream_reading(sights: list, end_t: float):
    """The ball's place from the stream itself: the median of the last few sightings (their world bearing and size), as a BallReading with via="stream". None when too few or too old."""
    import math
    import statistics

    from ..vision import ball_finder as bf
    recent = [s for s in sights if end_t - s[0] <= STREAM_WINDOW_S][-6:]
    if len(recent) < STREAM_MIN_N:
        return None
    med = lambda i: statistics.median(s[i] for s in recent)   # noqa: E731
    f = bf.FRAME_PX
    w, h = med(3) * f, med(4) * f
    diam = max(w, h, 1.0)
    return bf.BallReading(med(5) * f, med(6) * f, int(math.pi / 4.0 * diam * diam), int(w), int(h), diam, bf.DIST_K / diam, float(med(1)), False, "stream")


def _world_bearing(pan_log: lf.PanLog, t_capture: float, det) -> float:
    from .ball_chase import claw_pan_body
    cfg_fov = lf.LiveConfig().fov_half_deg
    return claw_pan_body(pan_log.at(t_capture)) + (float(det[2]) - 0.5) * 2.0 * cfg_fov


def watch_after_punt(robot, camera, make_grabber, find_fn, find_still, wcfg: WatchConfig | None = None, lcfg: lf.LiveConfig | None = None, *, pan_sign: str = "left", say=print,
                     announce=None, sleep=time.sleep, clock=time.monotonic, stopped=lambda: False, on_ready=None, judge_success=None) -> WatchResult:
    """The ball's active look after a punt: `behavior/active_look.run_active_look` follows the rolling ball (the arm to 120 degrees if it is not up, the claw steered from the stream) until it stops or is lost;
    this function then takes the ball-specific steps: one last picture, the stream's own last sightings as a fallback, "Got it.", the rest and the stand-up, and the announcements.
    `make_grabber(find_fn, cfg, clock, save)` -> a started-able grabber (the live follow's); `find_fn` is the tracking method (a tracker from behavior/ball_tracker.py, or a plain `find(jpeg)`);
    `judge_success(after)` -> True when the punt counts as a hit by the goal's own rule (`after` is {"distance_in", "bearing_deg"} of the ball, or None when it is out of sight): "Got it." is said as soon as
    two stream sightings in a row say so, or when the ball is lost, or at the end, always before "I lost the ball"; `camera` takes the still (`look()`); `find_still(camera) -> BallReading | None` finds the
    ball in a still (the chase's own find and confirm). `on_ready()` is called once the follow starts (the dry run says "roll the ball now"). Never raises. On return the claw is back at the centre and
    he is standing again when the follow ran to its end; a fall, a sag or the stop file ends it at once and the caller owns what comes after."""
    wcfg = wcfg or WatchConfig()
    lcfg = lcfg or lf.LiveConfig(seconds=wcfg.seconds, lead_s=wcfg.lead_s, jump_deg=wcfg.jump_deg, coast_s=wcfg.coast_s)
    res = WatchResult()
    t0 = clock()
    state = {"got_it": False, "succ_n": 0}
    judge = StopOrLostJudge(wcfg)

    def on_sighting(t_cap, b, d):
        if judge_success is None or state["got_it"]:
            return
        from ..vision import ball_finder as bf
        dist_now = bf.DIST_K / max(1.0, max(float(d[4]), float(d[5])) * bf.FRAME_PX)
        state["succ_n"] = state["succ_n"] + 1 if judge_success({"distance_in": dist_now, "bearing_deg": b}) else 0
        if state["succ_n"] >= 2:                                   # two sightings in a row show the ball went: the punt was good, say so now (2026-11-16)
            state["got_it"] = True
            if announce is not None:
                announce("Got it.")
    judge.on_sighting = on_sighting
    try:
        al = run_active_look(robot, make_grabber, find_fn, lcfg, judge=judge, pan_sign=pan_sign, say=say, sleep=sleep, clock=clock, stopped=stopped, on_ready=on_ready, seconds=wcfg.seconds,
                             stream_first=True)                    # the stream starts before the arm goes up: the ball is recorded while he moves (a punt leaves the arm up: nothing to raise)
        res.moves, res.pictures, res.bad_frames = al.moves, al.pictures, al.bad_frames
        res.rows, res.move_log = al.rows, al.move_log
        res.frames = frame_log(res.rows)
        res.sightings = len(al.sightings)
        res.last_bearing, res.last_side = al.last_bearing, al.last_side
        if al.ended in ("fell", "sag", "stopped_by_user", "error"):
            res.ended = al.ended
            return res
        sleep(0.5)                                                # (the stream was ended, AT+BREAK, before the still is requested)
        ball = None
        stream = None
        lost_by_stream = al.ended == "lost"
        res.ended = "stopped" if al.ended == "stopped" else ("lost" if lost_by_stream else "timeout")
        say(("watch: the stream lost the ball: one last picture before giving up" if lost_by_stream else f"watch: the ball {'has stopped' if res.ended == 'stopped' else 'is still rolling at the limit'}: taking a picture"))
        ball = find_still(camera)                                      # always: the claw is where the ball was last seen, and a ball that stopped in front of it may only have been missed by the stream
        for i in range(STILL_RETRIES):                                 # (owner, 2026-11-17) a far ball is missed by one picture: look again, claw where it was last seen, before giving up
            if ball is not None or stopped():
                break
            say(f"watch: no ball in the picture: looking again ({i + 1} of {STILL_RETRIES})")
            sleep(STILL_RETRY_WAIT_S)
            ball = find_still(camera)
        if not lost_by_stream:
            stream = stream_reading(al.sightings, al.ended_at)         # ... and where the stream saw it last (2026-11-16: the still alone missed far balls the stream had followed)
            res.stream_reading = stream
        if ball is None:
            res.still_diag = getattr(find_still, "last_diag", None)
            say("watch: no ball in the still" + (": using the stream's last sightings" if stream is not None else ": lost"))
        elif lost_by_stream:
            res.ended = "stopped"                                      # found again by the last picture: it had stopped where the claw was pointing
            say("watch: the last picture found the ball: it had stopped")
        if ball is not None:
            res.found, res.source = True, "still"
            res.reading = dataclasses.replace(ball, bearing_deg=ball.bearing_deg + _pan_body(al.pan))
        elif stream is not None:
            res.found, res.source, res.reading = True, "stream", stream     # the stream's bearing is already G2's own direction (the claw's pan is in it)
        else:
            res.ended = "lost"
        if judge_success is not None and not state["got_it"]:              # not said during the follow: judge the end result by the same rule ("Got it." comes before "I lost the ball", and before the rest and the stand-up)
            after = {"distance_in": res.reading.distance_in, "bearing_deg": res.reading.bearing_deg} if res.found else None
            if judge_success(after):
                state["got_it"] = True
                if announce is not None:
                    announce("Got it.")
        res.got_it = state["got_it"]
        # Either way (owner, 2026-11-15): claw centred, down into the rest position, the eased stand-up, and only then "target acquired" or the turn toward the last side
        settle = getattr(robot, "rest_then_stand", None)
        if callable(settle):
            if settle() == "fell":
                res.ended, res.found, res.reading = "fell", False, None
                return res
        else:
            robot.claw_pose(0.0, 0.0)
        if res.found:
            say(f"watch: target acquired ({res.source}): {res.reading.distance_in:.0f} in, {res.reading.bearing_deg:+.0f} deg from straight ahead")
            if announce is not None:
                announce("target acquired")
        else:
            say("watch: the ball is out of sight: lost")
            if announce is not None:
                announce("I lost the ball")
        return res
    except Exception:  # noqa: BLE001
        log.exception("the post-punt watch failed")
        res.ended = "error"
        return res
    finally:
        res.seconds = round(clock() - t0, 1)


def _pan_body(pan: float) -> float:
    from .ball_chase import claw_pan_body
    return claw_pan_body(pan)
