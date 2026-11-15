"""A supervised attentive bout (autonomy plan, 2026-11-15): G2 holds the attention pose with the claw raised and, for a few minutes, turns the camera toward what the camera model detects
(the largest detection first), looks around every so often, and then puts everything back. He never walks.

Why it is built like this:
  * From the attention pose the claw sits between the front legs and cannot pan, so the bout raises it to the look height first (the same first move as the claw look), then pans it.
    The arm moves through `SerialRobot.claw_pose` (the one shared arm move, pan clamped to the claw's range), the pose through `relax()` and the way out through `stand_up()`: the eased
    stand-up from the attention pose, the same as every mode.
  * The camera's frames are about a second old, so he follows slowly: a move at most every `cooldown_s`, only part of the way (`gain`), nothing under `deadband_deg`.
  * He does not stare: after `satiate_s` of following he only glances every `glance_s`, and follows again when the target moves `reengage_deg`.
  * The camera model has three classes and no person or face class (checked 2026-11-15), so the target is any detection of the model (`G2_ATTENTIVE_LABELS`, default: all), not a person.
  * A bout holds the focus lock (pi_pipeline/focus.py), stops on a fall, on the legs sagging (the body tilting `max_tilt_change_deg` from where it held) or on the stop file, and always ends with
    the claw down and centred and G2 stood up the standard way.

Runs ONLY on the owner's go, G2 on the floor, hands near, the voice service stopped (`g2attend`):

    python -m pi_pipeline.behavior.attentive_bout --minutes 2
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

log = logging.getLogger("g2.attentive_bout")

STOP_FILE = "~/.local/share/g2/attentive_stop"
LEG_KEEPALIVE_CMD = "i8 0 9 0 10 0 11 0 12 0 13 0 14 0 15 0"        # every leg joint at the attention pose's 0: sent again so the servos hold (the legs sag after about ten seconds of standing still)


@dataclass
class BoutConfig:
    minutes: float = 2.0
    pan_max_deg: float = 35.0          # the pan he will ask of the claw (its own limit is 45)
    fov_half_deg: float = 44.0         # the camera's half field of view, measured 2026-11-15 (the picture moves 0.0113 of its width per degree of pan)
    gain: float = 0.7                  # share of the way to the target one move goes (the frame he sees is about 1 s old)
    cooldown_s: float = 1.5            # least gap between two pan moves
    deadband_deg: float = 5.0          # a target this close to the middle needs no move
    satiate_s: float = 10.0            # following this long without a break: only glances after that
    glance_s: float = 5.0
    reengage_deg: float = 15.0         # a target this far off the middle follows again
    scan_every_s: float = 20.0         # nothing in view for this long: look around (left, right, middle)
    min_score: float = 0.35
    min_area: float = 0.004
    tick_s: float = 0.5
    keepalive_s: float = 4.0
    tilt_check_s: float = 1.0
    max_tilt_change_deg: float = 10.0
    labels: tuple | None = None        # None = any label of the model


def labels_from_env() -> tuple | None:
    v = os.environ.get("G2_ATTENTIVE_LABELS", "").strip()
    return tuple(x.strip().lower() for x in v.split(",") if x.strip()) or None


class GazeTracker:
    """Pure logic: detections in, the next claw pan out (or None to stay). `pan_sign` is "left" when a positive pan turns the camera left."""

    def __init__(self, cfg: BoutConfig, pan_sign: str = "left"):
        self.cfg, self.sign = cfg, pan_sign
        self._last_move = -1e9
        self._follow_since: float | None = None
        self._last_seen = None
        self._scan_i = 0
        self.reason = "start"

    def best(self, detections) -> tuple | None:
        """The largest usable detection: (label, score, cx, cy, w, h) in frame fractions."""
        ok = [d for d in (detections or []) if d[1] >= self.cfg.min_score and d[4] * d[5] >= self.cfg.min_area
              and (self.cfg.labels is None or str(d[0]).lower() in self.cfg.labels)]
        return max(ok, key=lambda d: d[4] * d[5]) if ok else None

    def update(self, detections, pan_now: float, now: float) -> float | None:
        c = self.cfg
        if self._last_seen is None:
            self._last_seen = now
        d = self.best(detections)
        if d is None:
            self._follow_since = None
            if now - self._last_seen >= c.scan_every_s and now - self._last_move >= c.cooldown_s:
                self._last_seen = now
                self._last_move = now
                pan = (c.pan_max_deg * 0.7, -c.pan_max_deg * 0.7, 0.0)[self._scan_i % 3]
                self._scan_i += 1
                self.reason = "look around"
                return pan
            self.reason = "nothing in view"
            return None
        self._last_seen = now
        off = (float(d[2]) - 0.5) * 2.0 * c.fov_half_deg                 # + = the target is to his right
        if abs(off) < c.deadband_deg:
            self.reason = f"{d[0]} centred"
            if self._follow_since is None:
                self._follow_since = now
            return None
        if self._follow_since is None or abs(off) >= c.reengage_deg and now - self._last_move >= c.glance_s:
            self._follow_since = now if self._follow_since is None else self._follow_since
        satiated = self._follow_since is not None and now - self._follow_since > c.satiate_s
        gap = c.glance_s if satiated and abs(off) < c.reengage_deg else c.cooldown_s
        if now - self._last_move < gap:
            self.reason = f"{d[0]}: waiting"
            return None
        if satiated and abs(off) >= c.reengage_deg:
            self._follow_since = now                                    # it moved a long way: follow it again
        self._last_move = now
        turn = -off * c.gain if self.sign == "left" else off * c.gain    # a positive pan turns the camera left on G2: toward a target on his right, pan the other way
        self.reason = f"follow {d[0]} ({off:+.0f} deg off)" if not satiated else f"glance at {d[0]}"
        return max(-c.pan_max_deg, min(c.pan_max_deg, pan_now + turn))


def stop_requested() -> bool:
    return os.path.exists(os.path.expanduser(STOP_FILE))


def run_bout(robot, look, cfg: BoutConfig | None = None, *, pan_sign: str = "left", say=print, sleep=time.sleep, clock=time.monotonic, stopped=stop_requested) -> dict:
    """One bout. `robot` is a chase `SerialRobot`; `look()` returns the detections of a fresh picture ((label, score, cx, cy, w, h) tuples, None when there was no picture). Returns what happened:
    {"ended": "time"|"stopped"|"fell"|"sag"|"no_board"|"error", "seconds", "moves", "scans", "pictures"}. The claw is lowered and centred and G2 is stood up the standard way however it ends (a fall leaves him
    in rest). Never raises."""
    from .. import focus
    cfg = cfg or BoutConfig()
    res = {"ended": "error", "seconds": 0.0, "moves": 0, "scans": 0, "pictures": 0}
    t0 = clock()
    pan = 0.0
    tracker = GazeTracker(cfg, pan_sign)
    try:
        with focus.holding("attentive_bout", "supervised attentive bout"):
            if robot._tilt(1.5) is None:
                say("attentive bout: no IMU frames from the board: is the BiBoard powered on? Nothing was moved.")
                res["ended"] = "no_board"
                return res
            say(f"attentive bout: {cfg.minutes:g} min, claw up, watching for {'anything the camera model detects' if not cfg.labels else ', '.join(cfg.labels)}")
            if robot.relax() == "fell" or robot._fell():
                res["ended"] = "fell"
                return res
            lift = getattr(robot, "look_lift_deg", None) or 120.0
            if robot.claw_pose(0.0, lift) == "fell":
                res["ended"] = "fell"
                return res
            base = robot._tilt()
            next_keep = clock() + cfg.keepalive_s
            next_tilt = clock() + cfg.tilt_check_s
            end_at = t0 + cfg.minutes * 60.0
            res["ended"] = "time"
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
                    robot._tx(LEG_KEEPALIVE_CMD)
                if now >= next_tilt:
                    next_tilt = now + cfg.tilt_check_s
                    t = robot._tilt()
                    if base is not None and t is not None and max(abs(t[0] - base[0]), abs(t[1] - base[1])) > cfg.max_tilt_change_deg:
                        say(f"attentive bout: the body tilted pitch {t[0]:+.0f} roll {t[1]:+.0f} (held at {base[0]:+.0f} {base[1]:+.0f}): ending the bout")
                        res["ended"] = "sag"
                        break
                dets = look()
                if dets is not None:
                    res["pictures"] += 1
                target = tracker.update(dets, pan, clock())
                if target is not None and abs(target - pan) >= 1.0:
                    scan = tracker.reason == "look around"
                    say(f"attentive bout: {tracker.reason}: pan {pan:+.0f} -> {target:+.0f}")
                    if robot.claw_pose(target, lift) == "fell":
                        res["ended"] = "fell"
                        break
                    pan = target
                    res["scans" if scan else "moves"] += 1
                sleep(cfg.tick_s)
    except Exception:  # noqa: BLE001
        log.exception("the attentive bout failed")
        res["ended"] = "error"
    finally:
        res["seconds"] = round(clock() - t0, 1)
        try:
            if res["ended"] != "fell":
                robot.claw_pose(0.0, 0.0)                              # claw down and centred first: never start a leg move with it up
                robot.stand_up()                                       # the standard eased stand-up out of the attention pose
        except Exception:  # noqa: BLE001
            log.exception("ending the attentive bout failed")
    say(f"attentive bout ended ({res['ended']}) after {res['seconds']:.0f} s: {res['moves']} follow moves, {res['scans']} look-arounds, {res['pictures']} pictures")
    return res


def main() -> None:
    import argparse

    from . import ball_chase as chase
    ap = argparse.ArgumentParser(description="One supervised attentive bout (claw gaze-follow from the attention pose). Needs the owner's go; the voice service stopped.")
    ap.add_argument("--minutes", type=float, default=2.0)
    ap.add_argument("--labels", default=None, help="comma-separated labels to follow (default: any detection; or G2_ATTENTIVE_LABELS)")
    ap.add_argument("--stream", action="store_true", help="with --live: use the module's continuous picture stream instead of one request per picture (about 4 pictures a second)")
    ap.add_argument("--live", action="store_true", help="follow continuously (pictures back to back, claw steered from where it pointed when each was taken); needs --target (behavior/live_follow.py)")
    ap.add_argument("--target", default=None, help="also find this named object with the object gallery (a name or part of one, for example the name of a toy): the camera's own detector knows only three classes")
    args = ap.parse_args()
    try:
        os.remove(os.path.expanduser(STOP_FILE))
    except OSError:
        pass
    from ..config import settings
    from ..link.serial_link import SerialLink
    from ..power import battery
    from ..vision.snapshot import CameraSnapshotter
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump, click=False)  # MODE-SPECIFIC(behavior/attentive_bout.py, 2026-11-15): no shutter click in this look
    from ..link import imu_print
    if not imu_print.board_answers(link):
        print("refused: no IMU frames from the BiBoard: is it powered on? Nothing was moved.")
        return
    robot = chase.SerialRobot(link)
    cfg = BoutConfig(minutes=args.minutes, labels=tuple(x.strip().lower() for x in args.labels.split(",")) if args.labels else labels_from_env())

    targets = None
    if args.target:
        from .gallery_target import open_targets
        targets = open_targets(target=args.target)
        print(f"also looking for '{args.target}' in the object gallery")
    outdir = os.path.expanduser(time.strftime("~/g2_claw_pics/bout_%Y%m%d_%H%M%S"))
    os.makedirs(outdir, exist_ok=True)
    seen = {"n": 0, "with_det": 0, "best": 0.0}

    def look():
        cam.discard_one()                                              # the module answers with the previous request's picture
        time.sleep(1.0)
        snap = cam.snapshot()
        if snap is None:
            return None
        seen["n"] += 1
        dets = list(snap.detections)
        if targets is not None:
            dets += targets.detections(snap.jpeg)                          # named matches from the object gallery, in the same (label, score, cx, cy, w, h) form
        if dets:
            seen["with_det"] += 1
            seen["best"] = max(seen["best"], max(d[1] for d in dets))
        try:
            with open(os.path.join(outdir, f"pic_{seen['n']:02d}.jpg"), "wb") as f:
                f.write(snap.jpeg)
        except OSError:
            pass
        print(f"picture {seen['n']}: " + (", ".join(f"{d[0]} {d[1]:.2f} at x={d[2]:.2f} area={d[4] * d[5]:.3f}" for d in dets) if dets else "no detections"))
        return dets
    try:
        chase._stand_if_lying(link, "kbalance")
        if args.live:
            from . import live_follow as lf
            if targets is None:
                print("refused: --live needs --target (for example ball)")
                return
            n = {"i": 0}

            def save(i, jpeg):
                with open(os.path.join(outdir, f"pic_{i:03d}.jpg"), "wb") as f:
                    f.write(jpeg)
            make = None
            if args.stream:
                cam._open()                                                # the snapshotter's start-up (reset wait, sensor option, exposure), then the stream takes the port
                make = lambda find, cfg, clock, sv: lf.StreamGrabber(cam._ser, find, cfg, clock=clock, save=sv)      # noqa: E731
            res = lf.run_live(robot, cam.snapshot, targets.detections, lf.LiveConfig(seconds=args.minutes * 60.0), pan_sign=chase.CLAW_PAN_SIGN, save=save, make_grabber=make)
            lf.write_log(res, outdir)
            print("STEP:", lf.step_report(res["rows"], res["moves"]))
            print(f"PICTURES: {outdir} ({res['summary'].get('pictures', 0)} pictures, {res['summary'].get('with_target', 0)} with the target)")
            return
        run_bout(robot, look, cfg, pan_sign=chase.CLAW_PAN_SIGN)
        print(f"PICTURES: {outdir} ({seen['n']} pictures, {seen['with_det']} with a detection, best score {seen['best']:.2f})")
    except KeyboardInterrupt:
        print("ended")
    finally:
        try:
            robot.claw_pose(0.0, 0.0)
        finally:
            cam.close()
            from .ball_chase import ensure_rest
            ensure_rest(link)


if __name__ == "__main__":
    main()
