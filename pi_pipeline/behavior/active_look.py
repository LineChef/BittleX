"""THE active look: one shared behavior every mode calls (2026-11-17, owner's design). Raise the arm to 120 degrees, then follow a target with the claw on the camera's picture stream, using whatever
TRACKING METHOD the caller passes in.

    result = run_active_look(robot, make_grabber, tracker, cfg, judge=...)

* The ARM: raised to `cfg.lift_deg` (120) first. Already up (a punt leaves it up): nothing is moved. Not up: with `cfg.attention_first` (the default, the standing rule that the claw look starts from the
  attention pose) he goes into the attention pose and then raises it.
* The TRACKER is the tracking method: a callable `tracker(jpeg, t_capture=None) -> detections`, each detection `(label, score, cx, cy, w, h)` with the centre and size in frame fractions (0 to 1). It
  may also have `bind(pan_log, follower, clock)` (called once the follow is set up: a tracker that needs the claw's pan at a picture's capture time, or the filter's prediction, takes them there) and
  `wants_capture_time = True` (the stream grabber then passes `t_capture=`). A plain `find(jpeg)` function is wrapped by `SimpleTracker`. The ball's tracker is `behavior/ball_tracker.py`; a face, a
  person or any other target is another small class with the same shape.
* The FOLLOW is the live follow's (behavior/live_follow.py): the claw is steered from where it pointed when each picture was taken; a tracking filter leads a moving target, coasts through missed
  pictures and holds a sighting that jumps far from where the target should be until a second one agrees. Every knob is in `LiveConfig` (gain, tick, deadband, lead, coast, jump, exposure lock).
* The END of the follow is decided by a JUDGE: `TimeOnlyJudge` (the default: follow for `seconds`) or `StopOrLostJudge` (the ball's: end when the target has stopped, or has been out of sight for
  `lost_after_s`). A judge is any object with `start(t_up, rows)` and `on_picture(pic, follower, now) -> str | None` (the end reason) and the attributes `sights`, `last_bearing`.
* SAFETY is the same for every mode (owner, 2026-11-17): a fall, a body that tilts more than `MAX_TILT_CHANGE_DEG` from how it stood, and the stop file end the follow whatever the tracker and the judge are,
  and a caller's config can lower those limits but never raise them (they are clamped here).
* The RESULT says how it ended, the last bearing and side the target was seen on, the sightings, the per-picture log. This function never walks, never takes a still, never lowers the claw and never
  stands up: the caller owns what comes after (the ball's watch does a last picture, rests him and stands him up).

Every mode that follows with the claw calls this (the ball watch after a punt, the supervised live follow): `tools/check_modes.py` rule R8 fails on a second follow loop.
"""
from __future__ import annotations

import dataclasses
import logging
import time
from collections import deque
from dataclasses import dataclass, field

from . import live_follow as lf

log = logging.getLogger("g2.active_look")

MAX_TILT_CHANGE_DEG = 10.0         # the follow ends ("sag") when the body tilts this far from how it stood: the same limit in every mode
MAX_TILT_CHECK_S = 1.0             # ... checked at least this often
DEFAULT_LIFT_DEG = 120.0           # the arm's height for the look; a mode may ask for another with `lift_deg=`


def frame_log(rows: list, limit: int = 90) -> list:
    """The stream's pictures as compact dicts for a journal or a log (every mode that follows keeps this): seconds from the first, bad (cut short), the target's centre x / y and width, the picture's
    brightness and size, and for a picture with no sighting the biggest green blob it held (area, x, y). Numbers only."""
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


# ------------------------------------------------------------------------------------------------------------ tracker contract
class SimpleTracker:
    """A plain `find(jpeg) -> detections` function as a tracker (no state, no use of the pan)."""
    wants_capture_time = False

    def __init__(self, find, name: str = "target"):
        self.find, self.name = find, name

    def __call__(self, jpeg: bytes, t_capture: float | None = None) -> list:
        return list(self.find(jpeg))


def as_tracker(find_or_tracker):
    """A tracker as it is, or a plain function wrapped."""
    if hasattr(find_or_tracker, "wants_capture_time") or hasattr(find_or_tracker, "bind"):
        return find_or_tracker
    return SimpleTracker(find_or_tracker)


# ------------------------------------------------------------------------------------------------------------ end-of-follow judges
@dataclass
class StopLostConfig:
    seconds: float = 20.0              # the longest the target is followed; the safety cap
    stable_n: int = 4                  # sightings (gaps allowed) over which it must not have moved to count as stopped
    max_window_s: float = 4.0          # ... and they must all fall within this long
    bearing_tol_deg: float = 2.0       # the world bearing may vary this much over those sightings
    size_tol: float = 0.15             # and its size this much (as a share of the mean): a target moving toward or away from him changes size
    min_span_s: float = 1.0
    lost_after_s: float = 4.0          # seen before, and not for this long: lost
    never_seen_s: float = 4.0          # never seen in the first this long of the follow: lost


class StopDetector:
    """Pure logic: (capture time, world bearing, size) samples in; `stopped` once the last `stable_n` agree (gaps between sightings allowed)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._s: deque = deque(maxlen=cfg.stable_n)

    def add(self, t: float, bearing: float, size: float) -> bool:
        self._s.append((t, bearing, size))
        return self.stopped

    def clear(self) -> None:
        self._s.clear()

    def miss(self) -> None:
        """A picture without the target: no reset (the stop detector counts sightings, not consecutive pictures); old sightings fall out of the window instead."""
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


class TimeOnlyJudge:
    """Follow until the time is up (or a fall, a sag, a stop): the judge never ends the follow itself. Records the sightings, so the result still says where the target was last seen."""

    def __init__(self):
        self.sights: list = []             # (capture time, world bearing, 0.0, width, height, cx, cy)
        self.last_bearing: float | None = None
        self.last_seen_t: float | None = None
        self.on_sighting = None            # an optional callback `(t_capture, bearing, detection)` for each accepted sighting

    def start(self, t_up: float, rows=None) -> None:
        self._t_up = t_up
        for row in list(rows or []):                           # what the stream saw before the claw was up (the claw had not panned: the world bearing is the offset)
            if row.get("det"):
                self.last_seen_t, self.last_bearing = row["t_capture"], (row["det"][0][1] - 0.5) * 2.0 * lf.LiveConfig().fov_half_deg

    def _sight(self, pic, follower, now):
        t_cap, dets, _idx = pic
        d = follower.tracked(t_cap, dets)
        if d is None:
            return None, None
        b = follower.world_bearing(t_cap, d)
        self.last_seen_t, self.last_bearing = now, b
        self.sights.append((t_cap, b, 0.0, float(d[4]), float(d[5]), float(d[2]), float(d[3])))
        if self.on_sighting is not None:
            self.on_sighting(t_cap, b, d)
        return d, b

    def on_picture(self, pic, follower, now) -> str | None:
        self._sight(pic, follower, now)
        return None


class StopOrLostJudge(TimeOnlyJudge):
    """The ball's end rule: "stopped" once its world bearing and size have stayed put over `stable_n` sightings; "lost" once it has been out of sight for `lost_after_s` after being seen, or was never
    seen in the first `never_seen_s` after the claw was up."""

    def __init__(self, cfg: StopLostConfig):
        super().__init__()
        self.cfg = cfg
        self.det = StopDetector(cfg)
        self.seen_in_loop = False

    def on_picture(self, pic, follower, now) -> str | None:
        d, b = self._sight(pic, follower, now)
        c = self.cfg
        if d is not None:
            self.seen_in_loop = True
            if self.det.add(pic[0], b, float(d[4])):
                return "stopped"
            return None
        self.det.miss()
        if self.seen_in_loop and self.last_seen_t is not None and now - self.last_seen_t > c.lost_after_s:       # seen while following, and not for this long
            return "lost"
        if not self.seen_in_loop and now - self._t_up > c.never_seen_s:                                            # the clock starts when the claw is up, not at the punch
            return "lost"
        return None


class CenteredJudge(TimeOnlyJudge):
    """For a look that is over once the claw has settled on the target (a greeting, "look at me"): ends "centred" when the target has stayed within `tol_deg` of the middle of the picture for `hold_s`.
    With `lost_after_s` set it also ends "lost" when the target has been out of sight that long after being seen. Otherwise only the time ends it."""

    def __init__(self, hold_s: float = 2.0, tol_deg: float = 6.0, lost_after_s: float | None = None):
        super().__init__()
        self.hold_s, self.tol, self.lost_after_s = hold_s, tol_deg, lost_after_s
        self._since: float | None = None
        self._seen = False

    def on_picture(self, pic, follower, now) -> str | None:
        d, _b = self._sight(pic, follower, now)
        if d is None:
            self._since = None
            if self.lost_after_s is not None and self._seen and self.last_seen_t is not None and now - self.last_seen_t > self.lost_after_s:
                return "lost"
            return None
        self._seen = True
        off = (float(d[2]) - 0.5) * 2.0 * follower.cfg.fov_half_deg
        if abs(off) > self.tol:
            self._since = None
            return None
        if self._since is None:
            self._since = now
        return "centred" if now - self._since >= self.hold_s else None


# ------------------------------------------------------------------------------------------------------------ the result
@dataclass
class ActiveLookResult:
    ended: str = "error"               # "time" | "stopped" | "lost" | "centred" (the judge's), "stopped_by_user" | "fell" | "sag" | "no_board" | "error"
    seconds: float = 0.0
    pictures: int = 0                  # pictures that arrived whole
    bad_frames: int = 0
    moves: int = 0
    pan: float = 0.0                   # where the claw ended
    reversals: int = 0
    sightings: list = field(default_factory=list)
    last_bearing: float | None = None  # the target's bearing in G2's own frame when last seen (+ = right)
    last_side: int = 0                 # +1 right, -1 left, 0 never seen
    rows: list = field(default_factory=list)
    move_log: list = field(default_factory=list)
    arm_raised: bool = False           # the arm was moved up (False: it was already up)
    frames: list = field(default_factory=list)      # the per-picture log (frame_log): numbers only, kept for every use
    ended_at: float = 0.0              # the clock when the follow ended (before the grabber was joined)


# ------------------------------------------------------------------------------------------------------------ the shared behavior
def run_active_look(robot, make_grabber, tracker, cfg: lf.LiveConfig | None = None, *, judge=None, pan_sign: str = "left", say=print, sleep=time.sleep, clock=time.monotonic,
                    stopped=lambda: False, save=None, snap_fn=None, on_ready=None, seconds: float | None = None, tilt_s: float = 0.2, raise_settle_s: float = 0.0,
                    stream_first: bool = False, lift_deg: float | None = None) -> ActiveLookResult:
    """Raise the arm to `cfg.lift_deg`, then follow with the claw using `tracker`, until the judge, the time, a fall, a sag or `stopped()` ends it. `make_grabber(find, cfg, clock, save)` builds the
    grabber (the stream's); None builds the picture-by-picture one from `snap_fn`. `on_ready()` is called once the follow starts. `stream_first` starts the stream before the arm goes up (the ball's
    watch keeps what it saw while he moved). `lift_deg` overrides the arm's height (default `cfg.lift_deg`, 120). Never raises; the caller owns the grabber's pictures and everything after the follow."""
    cfg = cfg or lf.LiveConfig()
    cfg = dataclasses.replace(cfg, lift_deg=cfg.lift_deg if lift_deg is None else float(lift_deg), max_tilt_change_deg=min(cfg.max_tilt_change_deg, MAX_TILT_CHANGE_DEG),
                              tilt_check_s=min(cfg.tilt_check_s, MAX_TILT_CHECK_S))      # a mode may lower the safety limits, never raise them
    tracker = as_tracker(tracker)
    judge = judge or TimeOnlyJudge()
    res = ActiveLookResult()
    t0 = clock()
    grab = None
    locked = False
    try:
        def make():
            g = make_grabber(tracker, cfg, clock, save) if make_grabber is not None else lf.Grabber(snap_fn, tracker, cfg, clock=clock, save=save)
            return g
        if stream_first:
            grab = make()
            grab.start()
        up = getattr(robot, "claw_is_up", None)
        if callable(up) and up():
            if robot._fell():                                    # the arm is already up (a punt leaves it up): tracking can start at once
                res.ended = "fell"
                return res
        else:
            if cfg.attention_first and callable(getattr(robot, "relax", None)):
                if robot.relax() == "fell" or robot._fell():
                    res.ended = "fell"
                    return res
            if robot.claw_pose(0.0, cfg.lift_deg) == "fell":
                res.ended = "fell"
                return res
            res.arm_raised = True
            if raise_settle_s:
                sleep(raise_settle_s)
        base = robot._tilt(tilt_s)
        t_up = clock()
        pan_log = lf.PanLog(0.0, t_up)
        follower = lf.LiveFollower(cfg, pan_sign, pan_log)
        if hasattr(tracker, "bind"):
            tracker.bind(pan_log, follower, clock)
        if grab is None:
            grab = make()
        if cfg.exposure_lock and callable(getattr(grab, "set_exposure_lock", None)):
            locked = bool(grab.set_exposure_lock(True))          # the experiment: freeze the sensor's auto exposure for the follow (always undone below)
        if not stream_first:
            grab.start()
        judge.start(t_up, list(getattr(grab, "rows", [])))
        reason = {"v": None}

        def on_picture(pic, pan, now):
            r = judge.on_picture(pic, follower, now)
            reason["v"] = r
            return r is not None
        if on_ready is not None:
            on_ready()
        out = lf.follow_loop(robot, grab, follower, pan_log, cfg, base=base, pan=0.0, seconds=seconds if seconds is not None else cfg.seconds, say=say, sleep=sleep, clock=clock,
                             stopped=stopped, on_picture=on_picture)
        rows = list(getattr(grab, "rows", []))
        res.rows, res.move_log, res.moves, res.pan, res.reversals = rows, out["moves"], len(out["moves"]), out["pan"], out["reversals"]
        res.frames = frame_log(rows)
        res.pictures = len([r for r in rows if not r.get("bad")])
        res.bad_frames = sum(1 for r in rows if r.get("bad"))
        res.sightings, res.last_bearing = list(judge.sights), judge.last_bearing
        res.last_side = 0 if judge.last_bearing is None else (1 if judge.last_bearing > 0 else -1)
        res.ended_at = clock()
        e = out["ended"]
        res.ended = reason["v"] if e == "done" else ("stopped_by_user" if e == "stopped" else e)     # "done" is the judge's end; "time", "fell", "sag" are the loop's own
        return res
    except Exception:  # noqa: BLE001
        log.exception("the active look failed")
        res.ended = "error"
        return res
    finally:
        if grab is not None:
            grab.stop_flag.set()
            try:
                grab.join(timeout=3.0)
            except Exception:  # noqa: BLE001
                pass
            if locked:
                try:
                    grab.set_exposure_lock(False)                # back to automatic exposure, however the follow ended
                except Exception:  # noqa: BLE001
                    log.exception("could not restore automatic exposure")
        res.seconds = round(clock() - t0, 1)
