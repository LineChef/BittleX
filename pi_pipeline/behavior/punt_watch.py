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
    seconds: float = 20.0              # the longest the ball is followed (owner, 2026-11-15: until it stops or rolls out of view; this is only the safety cap); then it counts as stopped where it is
    stable_n: int = 4                  # sightings (gaps allowed, a pale ball is seen only now and then) over which it must not have moved
    jump_deg: float = 30.0             # a sighting this far from the last tracked bearing, soon after it, must be seen twice before the claw follows it
    lead_s: float = 0.5                # the claw aims this far ahead of the rolling ball (its bearing speed times this); 0 = off
    max_window_s: float = 4.0          # ... and they must all fall within this long
    bearing_tol_deg: float = 2.0       # the world bearing may vary this much over those pictures
    size_tol: float = 0.15             # and its size this much (as a share of the mean): a ball rolling toward or away from him changes size
    min_span_s: float = 1.0
    lost_after_s: float = 4.0          # seen before, and not for this long: lost (2.5 s was too short for a ball the finder sees only now and then)
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

    def miss(self) -> None:
        """A picture without the ball: no reset (the stop detector counts sightings, not consecutive pictures); old sightings fall out of the window instead."""
        return None

    @property
    def stopped(self) -> bool:
        c = self.cfg
        if len(self._s) < c.stable_n:
            return False
        ts = [x[0] for x in self._s]
        bs = [x[1] for x in self._s]
        ws = [x[2] for x in self._s]
        mean_w = sum(ws) / len(ws)
        return (c.min_span_s <= ts[-1] - ts[0] <= c.max_window_s and max(bs) - min(bs) <= c.bearing_tol_deg and mean_w > 0 and (max(ws) - min(ws)) / mean_w <= c.size_tol)


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


def frame_log(rows: list, limit: int = 90) -> list:
    """The stream's pictures as compact dicts for the journal: seconds from the first, bad (cut short), the ball's centre x / y and width, the picture's brightness and size, and for a picture with no
    sighting the biggest green blob it held (area, x, y). Numbers only."""
    if not rows:
        return []
    t0 = rows[0].get("t_capture", 0.0)
    out = []
    for r in rows[:limit]:
        f = {"t": round(r.get("t_capture", t0) - t0, 1)}
        if r.get("bad"):
            f["bad"] = 1
        else:
            f["d"] = 1 if r.get("det") else 0
            if r.get("best"):
                f["ball"] = list(r["best"])
            if r.get("mean") is not None:
                f["mean"] = r["mean"]
            f["bytes"] = r.get("bytes")
            dg = r.get("diag")
            if dg:
                f["blob"] = [dg.get("area"), dg.get("x"), dg.get("y")]
        out.append(f)
    return out


def _world_bearing(pan_log: lf.PanLog, t_capture: float, det) -> float:
    from .ball_chase import claw_pan_body
    cfg_fov = lf.LiveConfig().fov_half_deg
    return claw_pan_body(pan_log.at(t_capture)) + (float(det[2]) - 0.5) * 2.0 * cfg_fov


def watch_after_punt(robot, camera, make_grabber, find_fn, find_still, wcfg: WatchConfig | None = None, lcfg: lf.LiveConfig | None = None, *, pan_sign: str = "left", say=print,
                     announce=None, sleep=time.sleep, clock=time.monotonic, stopped=lambda: False, on_ready=None, judge_success=None) -> WatchResult:
    """`make_grabber(find_fn, cfg, clock, save)` -> a started-able grabber (the live follow's); `judge_success(after)` -> True when the punt counts as a hit by the goal's own rule (`after` is {"distance_in", "bearing_deg"} of the ball, or None when it is out of sight): "Got it." is said as soon as two stream sightings in a row say so, or when the ball is lost, or at the end, always before "I lost the ball"; `camera` takes the still (`look()`); `find_still(camera) -> BallReading | None` finds the ball in a still
    (the chase's own find and confirm). `on_ready()` is called once the claw is up and the follow starts (the dry run says "roll the ball now"). Never raises. On return the claw is back at the centre and lowered when the ball was found; otherwise it is left up for the caller's turn and look."""
    wcfg = wcfg or WatchConfig()
    lcfg = lcfg or lf.LiveConfig(seconds=wcfg.seconds, lead_s=wcfg.lead_s, jump_deg=wcfg.jump_deg)
    res = WatchResult()
    t0 = clock()
    grab = None
    try:
        grab = make_grabber(find_fn, lcfg, clock, None)
        grab.start()                                             # the stream starts at once: the ball is recorded while he moves into the attention pose
        if callable(getattr(robot, "claw_is_up", None)) and robot.claw_is_up():
            if robot._fell():                                    # the punt left the arm up: no attention-pose move, no raise: tracking can start at once
                res.ended = "fell"
                return res
        else:
            if robot.relax() == "fell" or robot._fell():
                res.ended = "fell"
                return res
            if robot.claw_pose(0.0, lcfg.lift_deg) == "fell":
                res.ended = "fell"
                return res
        base = robot._tilt(0.2)
        t_up = clock()
        pan_log = lf.PanLog(0.0, t_up)
        follower = lf.LiveFollower(lcfg, pan_sign, pan_log)
        det = StopDetector(wcfg)
        state = {"last_seen_t": None, "last_bearing": None, "reason": None, "seen_in_loop": False, "sights": [], "got_it": False, "succ_n": 0}
        for row in list(grab.rows):                              # what the stream saw before the claw was up (the claw has not panned: the world bearing is the offset)
            if row["det"]:
                off = (row["det"][0][1] - 0.5) * 2.0 * lcfg.fov_half_deg
                state["last_seen_t"], state["last_bearing"] = row["t_capture"], off

        def on_picture(pic, pan, now):
            t_cap, dets, idx = pic
            d = follower.tracked(t_cap, dets)
            if d is not None:
                b = _world_bearing(pan_log, t_cap, d)
                state["last_seen_t"], state["last_bearing"] = now, b
                state["seen_in_loop"] = True
                state["sights"].append((t_cap, b, 0.0, float(d[4]), float(d[5]), float(d[2]), float(d[3])))      # (time, world bearing, -, width, height, cx, cy): the stream's own sightings
                if judge_success is not None and not state["got_it"]:
                    from ..vision import ball_finder as bf
                    dist_now = bf.DIST_K / max(1.0, max(float(d[4]), float(d[5])) * bf.FRAME_PX)
                    state["succ_n"] = state["succ_n"] + 1 if judge_success({"distance_in": dist_now, "bearing_deg": b}) else 0
                    if state["succ_n"] >= 2:                                   # two sightings in a row show the ball went: the punt was good, say so now (2026-11-16)
                        state["got_it"] = True
                        if announce is not None:
                            announce("Got it.")
                if det.add(t_cap, b, float(d[4])):
                    state["reason"] = "stopped"
                    return True
            else:
                det.miss()
                ref = state["last_seen_t"]
                if state["seen_in_loop"] and now - ref > wcfg.lost_after_s:            # seen while following, and not for this long
                    state["reason"] = "lost"
                    return True
                if not state["seen_in_loop"] and now - t_up > wcfg.never_seen_s:       # the clock starts when the claw is up, not at the punch (the first sightings were before it could pan)
                    state["reason"] = "lost"
                    return True
            return False
        if on_ready is not None:
            on_ready()
        out = lf.follow_loop(robot, grab, follower, pan_log, lcfg, base=base, pan=0.0, seconds=wcfg.seconds, say=say, sleep=sleep, clock=clock, stopped=stopped, on_picture=on_picture)
        res.moves = len(out["moves"])
        res.pictures = len([r for r in grab.rows if not r.get("bad")])
        res.bad_frames = sum(1 for r in grab.rows if r.get("bad"))
        res.rows, res.move_log = list(grab.rows), out["moves"]
        res.frames = frame_log(res.rows)
        end_t = clock()                                           # (before the stream is joined: the sightings' ages are measured from the end of the follow)
        res.sightings = len(state["sights"])
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
        ball = None
        stream = None
        lost_by_stream = state["reason"] == "lost"
        res.ended = "stopped" if state["reason"] == "stopped" else ("lost" if lost_by_stream else "timeout")
        say(("watch: the stream lost the ball: one last picture before giving up" if lost_by_stream else f"watch: the ball {'has stopped' if res.ended == 'stopped' else 'is still rolling at the limit'}: taking a picture"))
        ball = find_still(camera)                                      # always: the claw is where the ball was last seen, and a ball that stopped in front of it may only have been missed by the stream
        if not lost_by_stream:
            stream = stream_reading(state["sights"], end_t)            # ... and where the stream saw it last (2026-11-16: the still alone missed far balls the stream had followed)
            res.stream_reading = stream
        if ball is None:
            res.still_diag = getattr(find_still, "last_diag", None)
            say("watch: no ball in the still" + (": using the stream's last sightings" if stream is not None else ": lost"))
        elif lost_by_stream:
            res.ended = "stopped"                                      # found again by the last picture: it had stopped where the claw was pointing
            say("watch: the last picture found the ball: it had stopped")
        if ball is not None:
            res.found, res.source = True, "still"
            res.reading = dataclasses.replace(ball, bearing_deg=ball.bearing_deg + _pan_body(out["pan"]))
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
