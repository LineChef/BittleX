"""Live follow (2026-11-15): the claw follows the target continuously instead of one move every second or two.

The attentive bout (behavior/attentive_bout.py) takes a picture, waits for it, moves the claw, waits again: about one update every 1.4 s. This mode splits that in two:

  * a CAMERA THREAD asks the camera for pictures back to back (the module answers a request with the previous request's picture, about 0.35 s apart, so about 2 to 3 pictures a second) and finds
    the target in each (the green ball by the colour finder, or a named gallery object);
  * a CONTROL LOOP, ten times a second, takes the newest picture it has not used and steers the claw to where the target was when the picture was taken: it works out the claw's pan AT THE TIME OF
    THE PICTURE (`PanLog`), adds the correction for the offset seen there, and asks for that absolute pan. A picture that shows the claw's old position therefore does not make it overshoot.

The picture is old by the time it is used (about 0.5 to 1 s), so the gain is low and nothing is predicted: this follows a ball moved at walking speed, not a thrown one. Everything the bout does for
safety stays: the focus lock, a fall, a sag, the stop file, and the claw down and the standard stand-up at the end. It never walks.

    python -m pi_pipeline.behavior.attentive_bout --minutes 1 --target ball --live        # `g2attend 1 ball live`
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger("g2.live_follow")


@dataclass
class LiveConfig:
    seconds: float = 60.0
    pan_max_deg: float = 35.0
    fov_half_deg: float = 44.0         # measured 2026-11-15: the picture moves 0.0113 of its width per degree of pan, so half the field of view is about 44 deg (full about 89), not 31.5
    gain: float = 0.5                  # share of the offset seen in a picture that one correction asks for (the picture is old: lower than the bout's 0.7)
    deadband_deg: float = 3.0
    min_move_deg: float = 1.0
    tick_s: float = 0.1
    stale_s: float = 2.5               # a picture older than this when it is used is ignored
    capture_lag_requests: int = 1      # the module answers a request with the previous request's picture
    capture_delay_s: float = 0.15      # from the request to the exposure
    keepalive_s: float = 4.0
    tilt_check_s: float = 1.0
    max_tilt_change_deg: float = 10.0
    lift_deg: float = 120.0


class PanLog:
    """Where the claw's pan was at any past time, from the moves it was sent through: each move is (start, end, from, to) with a straight line between."""

    def __init__(self, pan0: float = 0.0, t0: float = 0.0):
        self._ev: list[tuple] = [(t0, t0, float(pan0), float(pan0))]

    def move(self, t_start: float, t_end: float, pan_from: float, pan_to: float) -> None:
        self._ev.append((t_start, max(t_end, t_start), float(pan_from), float(pan_to)))

    def at(self, t: float) -> float:
        pan = self._ev[0][2]
        for t0, t1, a, b in self._ev:
            if t < t0:
                break
            pan = b if t >= t1 or t1 <= t0 else a + (b - a) * (t - t0) / (t1 - t0)
        return pan


class LiveFollower:
    """Pure logic: a picture's detections and its capture time in, the absolute pan to ask for (or None) out."""

    def __init__(self, cfg: LiveConfig, pan_sign: str, pan_log: PanLog):
        self.cfg, self.sign, self.pan_log = cfg, pan_sign, pan_log
        self.last_used_t = -1e9
        self.reason = "start"

    def best(self, dets):
        return max(dets, key=lambda d: d[4] * d[5], default=None) if dets else None

    def decide(self, t_capture: float, dets, now: float, pan_now: float):
        c = self.cfg
        if t_capture <= self.last_used_t:
            self.reason = "no new picture"
            return None
        self.last_used_t = t_capture
        if now - t_capture > c.stale_s:
            self.reason = "picture too old"
            return None
        d = self.best(dets)
        if d is None:
            self.reason = "nothing in view"
            return None
        off = (float(d[2]) - 0.5) * 2.0 * c.fov_half_deg                       # + = the target is to his right, as the picture showed it
        if abs(off) < c.deadband_deg:
            self.reason = f"{d[0]} centred ({off:+.0f} deg)"
            return None
        pan_c = self.pan_log.at(t_capture)                                      # where the claw pointed when the picture was taken, not where it is now
        turn = -off * c.gain if self.sign == "left" else off * c.gain
        want = max(-c.pan_max_deg, min(c.pan_max_deg, pan_c + turn))
        if abs(want - pan_now) < c.min_move_deg:
            self.reason = f"{d[0]}: already there"
            return None
        self.reason = f"follow {d[0]} ({off:+.0f} deg off, pan at the picture {pan_c:+.0f})"
        return want


class Grabber(threading.Thread):
    """Pictures back to back. `snap_fn()` -> an object with `.jpeg`, or None; `find_fn(jpeg)` -> detections. The newest result is in `latest`."""

    def __init__(self, snap_fn, find_fn, cfg: LiveConfig, *, clock=time.monotonic, save=None):
        super().__init__(name="live-grabber", daemon=True)
        self.snap_fn, self.find_fn, self.cfg, self.clock, self.save = snap_fn, find_fn, cfg, clock, save
        self.stop_flag = threading.Event()
        self.latest: tuple | None = None            # (t_capture, detections, index)
        self.rows: list[dict] = []
        self._starts: list[float] = []
        self._lock = threading.Lock()

    def take(self):
        with self._lock:
            return self.latest

    def run(self) -> None:
        n = 0
        while not self.stop_flag.is_set():
            t_call = self.clock()
            self._starts.append(t_call)
            try:
                snap = self.snap_fn()
            except Exception:  # noqa: BLE001
                log.debug("live grab failed", exc_info=True)
                snap = None
            t_done = self.clock()
            if snap is None:
                continue
            k = self.cfg.capture_lag_requests
            t_cap = (self._starts[-1 - k] + self.cfg.capture_delay_s) if len(self._starts) > k else t_call
            try:
                dets = list(self.find_fn(snap.jpeg))
            except Exception:  # noqa: BLE001
                dets = []
            n += 1
            if self.save is not None:
                try:
                    self.save(n, snap.jpeg)
                except Exception:  # noqa: BLE001
                    pass
            row = {"n": n, "t_call": round(t_call, 3), "t_done": round(t_done, 3), "t_capture": round(t_cap, 3), "grab_s": round(t_done - t_call, 3),
                   "det": [(d[0], round(d[2], 3)) for d in dets]}
            with self._lock:
                self.latest = (t_cap, dets, n)
                self.rows.append(row)


def summarize(rows: list[dict], moves: list[dict], reversals: int, seconds: float) -> dict:
    grabs = [r["grab_s"] for r in rows] or [0.0]
    seen = [r for r in rows if r["det"]]
    return {"pictures": len(rows), "pictures_per_s": round(len(rows) / seconds, 2) if seconds > 0 else 0.0, "with_target": len(seen),
            "grab_s_mean": round(statistics.mean(grabs), 2), "grab_s_max": round(max(grabs), 2), "moves": len(moves), "reversals": reversals,
            "use_age_s_mean": round(statistics.mean([m["age_s"] for m in moves]), 2) if moves else None}


def run_live(robot, snap_fn, find_fn, cfg: LiveConfig | None = None, *, pan_sign: str = "left", say=print, sleep=time.sleep, clock=time.monotonic,
             stopped=lambda: False, save=None) -> dict:
    """One live follow run. Returns {"ended", "seconds", "summary", "moves", "rows"}. Never raises; the claw is lowered and G2 stands up the standard way however it ends (a fall leaves him in rest)."""
    from .. import focus
    cfg = cfg or LiveConfig()
    res = {"ended": "error", "seconds": 0.0, "summary": {}, "moves": [], "rows": []}
    t0 = clock()
    grab: Grabber | None = None
    moves: list[dict] = []
    reversals = 0
    try:
        with focus.holding("attentive_bout", "supervised live follow"):
            if robot._tilt(1.5) is None:
                say("live follow: no IMU frames from the board: is the BiBoard powered on? Nothing was moved.")
                res["ended"] = "no_board"
                return res
            if robot.relax() == "fell" or robot._fell():
                res["ended"] = "fell"
                return res
            if robot.claw_pose(0.0, cfg.lift_deg) == "fell":
                res["ended"] = "fell"
                return res
            sleep(0.5)
            base = robot._tilt()
            pan_log = PanLog(0.0, clock())
            follower = LiveFollower(cfg, pan_sign, pan_log)
            grab = Grabber(snap_fn, find_fn, cfg, clock=clock, save=save)
            grab.start()
            pan, last_dir = 0.0, 0
            t_start = clock()
            end_at = t_start + cfg.seconds
            next_keep, next_tilt = t_start + cfg.keepalive_s, t_start + cfg.tilt_check_s
            res["ended"] = "time"
            say(f"live follow: {cfg.seconds:.0f} s, claw up")
            while clock() < end_at:
                if stopped():
                    res["ended"] = "stopped"
                    break
                if robot._fell():
                    res["ended"] = "fell"
                    break
                now = clock()
                if now >= next_keep:
                    next_keep = now + cfg.keepalive_s
                    robot._tx("i8 0 9 0 10 0 11 0 12 0 13 0 14 0 15 0")
                if now >= next_tilt:
                    next_tilt = now + cfg.tilt_check_s
                    if base is not None and robot._roll and robot._pitch:
                        r = statistics.median(robot._roll[-5:])
                        p = statistics.median(robot._pitch[-5:])
                        if max(abs(p - base[0]), abs(r - base[1])) > cfg.max_tilt_change_deg:
                            say(f"live follow: the body tilted pitch {p:+.0f} roll {r:+.0f}: ending")
                            res["ended"] = "sag"
                            break
                pic = grab.take()
                if pic is not None:
                    t_cap, dets, idx = pic
                    want = follower.decide(t_cap, dets, now, pan)
                    if want is not None:
                        ts = clock()
                        state = robot.claw_pose(want, cfg.lift_deg)
                        te = clock()
                        pan_log.move(ts, te, pan, want)
                        d = 1 if want > pan else -1
                        if last_dir and d != last_dir:
                            reversals += 1
                        last_dir = d
                        moves.append({"picture": idx, "t": round(ts - t_start, 2), "age_s": round(ts - t_cap, 2), "from": round(pan, 1), "to": round(want, 1), "why": follower.reason})
                        pan = want
                        if state == "fell":
                            res["ended"] = "fell"
                            break
                sleep(cfg.tick_s)
    except Exception:  # noqa: BLE001
        log.exception("the live follow failed")
        res["ended"] = "error"
    finally:
        if grab is not None:
            grab.stop_flag.set()
            grab.join(timeout=3.0)
        res["seconds"] = round(clock() - t0, 1)
        try:
            if res["ended"] not in ("fell", "no_board"):
                robot.claw_pose(0.0, 0.0)
                robot.stand_up()
        except Exception:  # noqa: BLE001
            log.exception("ending the live follow failed")
    if grab is not None:
        res["rows"], res["moves"] = grab.rows, moves
        res["summary"] = summarize(grab.rows, moves, reversals, max(res["seconds"], 1e-6))
    say(f"live follow ended ({res['ended']}) after {res['seconds']:.0f} s: {res['summary']}")
    return res


def step_report(rows: list[dict], moves: list[dict], fov_half_deg: float = 44.0, settle_deg: float = 6.0, settle_n: int = 3) -> dict:
    """The step response of a run with a FIXED target: the first offset, the time until the target stays within `settle_deg` of the middle for `settle_n` pictures in a row, the biggest offset after that,
    the steady offset at the end and the number of direction reversals (an oscillation shows as many)."""
    pts = [(r["t_capture"], (r["det"][0][1] - 0.5) * 2.0 * fov_half_deg) for r in rows if r["det"]]
    if not pts:
        return {"pictures_with_target": 0}
    t0 = pts[0][0]
    settled_at = None
    for i in range(len(pts) - settle_n + 1):
        if all(abs(p[1]) <= settle_deg for p in pts[i:i + settle_n]):
            settled_at = pts[i][0] - t0
            break
    after = [abs(p[1]) for p in pts if settled_at is not None and p[0] - t0 >= settled_at]
    tail = [abs(p[1]) for p in pts[-5:]]
    dirs = [1 if m["to"] > m["from"] else -1 for m in moves]
    return {"first_offset_deg": round(pts[0][1], 1), "settled_after_s": None if settled_at is None else round(settled_at, 1),
            "worst_offset_after_settling_deg": round(max(after), 1) if after else None, "final_offset_deg": round(statistics.median(tail), 1),
            "reversals": sum(1 for a, b in zip(dirs, dirs[1:]) if a != b), "moves": len(moves), "pictures_with_target": len(pts)}


def write_log(res: dict, outdir: str) -> str | None:
    try:
        path = os.path.join(os.path.expanduser(outdir), "live_log.json")
        with open(path, "w") as f:
            json.dump({"ended": res["ended"], "seconds": res["seconds"], "summary": res["summary"], "moves": res["moves"], "rows": res["rows"]}, f)
        return path
    except OSError:
        return None
