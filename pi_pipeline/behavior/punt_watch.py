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

log = logging.getLogger("g2.punt_watch")


@dataclass
class WatchConfig:
    seconds: float = 10.0              # the longest the ball is followed; then it counts as stopped where it is
    stable_n: int = 6                  # pictures in a row over which it must not have moved (about 1.5 s of the stream)
    bearing_tol_deg: float = 2.0       # the world bearing may vary this much over those pictures
    size_tol: float = 0.15             # and its size this much (as a share of the mean): a ball rolling toward or away from him changes size
    min_span_s: float = 1.0
    lost_after_s: float = 2.5          # seen before, and not for this long: lost
    never_seen_s: float = 4.0          # never seen in the first this long of the follow: lost
    lost_turn_deg: float = 40.0        # the turn the caller makes toward the last-seen side


class StopDetector:
    """Pure logic: (capture time, world bearing, size) samples in; `stopped` once the last `n` agree."""

    def __init__(self, cfg: WatchConfig):
        self.cfg = cfg
        self._s: deque = deque(maxlen=cfg.stable_n)

    def add(self, t: float, bearing: float, size: float) -> bool:
        self._s.append((t, bearing, size))
        return self.stopped

    def clear(self) -> None:
        self._s.clear()

    @property
    def stopped(self) -> bool:
        c = self.cfg
        if len(self._s) < c.stable_n:
            return False
        ts = [x[0] for x in self._s]
        bs = [x[1] for x in self._s]
        ws = [x[2] for x in self._s]
        mean_w = sum(ws) / len(ws)
        return (ts[-1] - ts[0] >= c.min_span_s and max(bs) - min(bs) <= c.bearing_tol_deg and mean_w > 0 and (max(ws) - min(ws)) / mean_w <= c.size_tol)


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


def _world_bearing(pan_log: lf.PanLog, t_capture: float, det) -> float:
    from .ball_chase import claw_pan_body
    cfg_fov = lf.LiveConfig().fov_half_deg
    return claw_pan_body(pan_log.at(t_capture)) + (float(det[2]) - 0.5) * 2.0 * cfg_fov


def watch_after_punt(robot, camera, make_grabber, find_fn, find_still, wcfg: WatchConfig | None = None, lcfg: lf.LiveConfig | None = None, *, pan_sign: str = "left", say=print,
                     announce=None, sleep=time.sleep, clock=time.monotonic, stopped=lambda: False) -> WatchResult:
    """`make_grabber(find_fn, cfg, clock, save)` -> a started-able grabber (the live follow's); `camera` takes the still (`look()`); `find_still(camera) -> BallReading | None` finds the ball in a still
    (the chase's own find and confirm). Never raises. On return the claw is back at the centre and lowered when the ball was found; otherwise it is left up for the caller's turn and look."""
    wcfg = wcfg or WatchConfig()
    lcfg = lcfg or lf.LiveConfig(seconds=wcfg.seconds)
    res = WatchResult()
    t0 = clock()
    grab = None
    try:
        grab = make_grabber(find_fn, lcfg, clock, None)
        grab.start()                                             # the stream starts at once: the ball is recorded while he moves into the attention pose
        if robot.relax() == "fell" or robot._fell():
            res.ended = "fell"
            return res
        if robot.claw_pose(0.0, lcfg.lift_deg) == "fell":
            res.ended = "fell"
            return res
        sleep(0.3)
        base = robot._tilt()
        t_up = clock()
        pan_log = lf.PanLog(0.0, t_up)
        follower = lf.LiveFollower(lcfg, pan_sign, pan_log)
        det = StopDetector(wcfg)
        state = {"last_seen_t": None, "last_bearing": None, "reason": None}
        for row in list(grab.rows):                              # what the stream saw before the claw was up (the claw has not panned: the world bearing is the offset)
            if row["det"]:
                off = (row["det"][0][1] - 0.5) * 2.0 * lcfg.fov_half_deg
                state["last_seen_t"], state["last_bearing"] = row["t_capture"], off

        def on_picture(pic, pan, now):
            t_cap, dets, idx = pic
            d = follower.best(dets)
            if d is not None:
                b = _world_bearing(pan_log, t_cap, d)
                state["last_seen_t"], state["last_bearing"] = now, b
                if det.add(t_cap, b, float(d[4])):
                    state["reason"] = "stopped"
                    return True
            else:
                det.clear()
                ref = state["last_seen_t"]
                if ref is not None and now - ref > wcfg.lost_after_s:
                    state["reason"] = "lost"
                    return True
                if ref is None and now - t_up > wcfg.never_seen_s:
                    state["reason"] = "lost"
                    return True
            return False
        out = lf.follow_loop(robot, grab, follower, pan_log, lcfg, base=base, pan=0.0, seconds=wcfg.seconds, say=say, sleep=sleep, clock=clock, stopped=stopped, on_picture=on_picture)
        res.moves = len(out["moves"])
        res.pictures = len(grab.rows)
        res.last_bearing = state["last_bearing"]
        res.last_side = 0 if state["last_bearing"] is None else (1 if state["last_bearing"] > 0 else -1)
        if out["ended"] in ("fell", "sag"):
            res.ended = out["ended"]
            return res
        if out["ended"] == "stopped":
            res.ended = "stopped_by_user"
            return res
        grab.stop_flag.set()
        grab.join(timeout=3.0)                                    # the stream is ended (AT+BREAK) before the still is requested
        sleep(0.5)
        if state["reason"] == "lost":
            res.ended = "lost"
            say("watch: the ball is out of sight: lost")
            if announce is not None:
                announce("I lost it")
            return res
        res.ended = "stopped" if state["reason"] == "stopped" else "timeout"
        say(f"watch: the ball {'has stopped' if res.ended == 'stopped' else 'is still rolling at the limit'}: taking a picture")
        ball = find_still(camera)
        if ball is None:
            res.ended = "lost"
            say("watch: no ball in the still: lost")
            if announce is not None:
                announce("I lost it")
            return res
        res.found = True
        res.reading = dataclasses.replace(ball, bearing_deg=ball.bearing_deg + _pan_body(out["pan"]))
        say(f"watch: target acquired: {ball.distance_in:.0f} in, {res.reading.bearing_deg:+.0f} deg from straight ahead")
        if announce is not None:
            announce("target acquired")
        robot.claw_pose(0.0, 0.0)                                 # the chase's first reading is from straight ahead with the claw home
        return res
    except Exception:  # noqa: BLE001
        log.exception("the post-punt watch failed")
        res.ended = "error"
        return res
    finally:
        if grab is not None:
            grab.stop_flag.set()
            try:
                grab.join(timeout=3.0)
            except Exception:  # noqa: BLE001
                pass
        res.seconds = round(clock() - t0, 1)


def _pan_body(pan: float) -> float:
    from .ball_chase import claw_pan_body
    return claw_pan_body(pan)
