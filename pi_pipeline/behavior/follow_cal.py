"""Follow calibration (hardware test, 2026-11-17): how fast does the claw's follow loop really react? Two numbers decide how to tune the active look (the gain, the lead, the coast, the tick):

  * the DELAY from a pan command to the first stream picture that shows the scene moved (the servo's start, the exposure, the encode and the serial transfer, all together), and
  * the pan SPEED the picture shows between 10% and 90% of the step.

G2 stands with a fixed ball in front of him (about 14 to 24 in, centred) and the arm goes to 120 degrees like the active look's; the camera streams; the claw takes pan steps (default 10, 20 and 30 degrees,
left and right, twice each) back to the centre; each step's picture log gives the delay and the speed. Numbers only: no picture is saved. A fall, a lost ball (the ball must stay in view), a tilt of the
body or the stop file ends it; he is laid in rest at the end. Runs ONLY on the owner's go, G2 on the floor, hands near, the voice service stopped (`g2followcal`).

    python -m pi_pipeline.behavior.follow_cal [--steps 10,20,30] [--repeats 2] [--lock-ae]

`--lock-ae` freezes the sensor's auto exposure for the run (undone at the end): run it once without and once with, and compare the brightness spread in the summary under the same pan steps.
"""
from __future__ import annotations

import json
import os
import statistics
import time

FOV_DEG = 89.0                  # the measured full field of view over the frame width (the picture moves 1/89 of its width per degree of pan)
STOP_FILE = "~/.local/share/g2/followcal_stop"


def step_metrics(ts: float, te: float, pan_from: float, pan_to: float, rows: list, fov_deg: float = FOV_DEG, sign: str = "left") -> dict:
    """One step's numbers from the picture log. `rows` = [(arrival time, ball centre x as a share of the frame width or None)]; `ts`..`te` the command's start and end. The scene moves RIGHT in the
    picture when a "left" claw pans positively; the expected total shift is (pan_to - pan_from) / fov_deg of the width."""
    step = pan_to - pan_from
    expect = (step / fov_deg) * (1 if sign == "left" else -1)
    seen = [(t, x) for t, x in rows if x is not None]
    before = [x for t, x in seen if t <= ts]
    after = [(t, x) for t, x in seen if t > ts]
    out = {"step_deg": round(step, 1), "command_s": round(te - ts, 2), "delay_s": None, "speed_deg_s": None, "settled_deg": None, "pictures_after": len(after)}
    if not before or len(after) < 3 or expect == 0:
        return out
    x0 = statistics.median(before[-3:])
    frac = [(t, (x - x0) / expect) for t, x in after]                         # 0 = not moved, 1 = moved the whole step
    t10 = next((t for t, f in frac if f >= 0.10), None)
    t90 = next((t for t, f in frac if f >= 0.90), None)
    if t10 is not None:
        out["delay_s"] = round(t10 - ts, 2)
    if t10 is not None and t90 is not None and t90 > t10:
        out["speed_deg_s"] = round(abs(step) * 0.8 / (t90 - t10), 1)
    out["settled_deg"] = round(frac[-1][1] * abs(step), 1) if frac else None  # how far the picture says it went (the last picture), as degrees of the step
    return out


def brightness_stats(rows: list) -> dict | None:
    """The spread of the pictures' brightness over the run (the stream grabber logs each picture's mean): min, max, standard deviation, and how many pictures had none (cut short)."""
    vals = [r["mean"] for r in rows if r.get("mean") is not None]
    if not vals:
        return None
    return {"n": len(vals), "no_brightness": len([r for r in rows if not r.get("bad") and r.get("mean") is None]), "min": min(vals), "max": max(vals), "mean": round(statistics.mean(vals), 1), "stdev": round(statistics.pstdev(vals), 2)}


def summarize(trials: list) -> dict:
    out = {}
    for key in ("delay_s", "speed_deg_s", "command_s"):
        v = [t[key] for t in trials if t.get(key) is not None]
        if v:
            out[key] = {"median": round(statistics.median(v), 2), "min": min(v), "max": max(v), "n": len(v)}
    by = {}
    for t in trials:
        if t.get("speed_deg_s") is not None:
            by.setdefault(abs(t["step_deg"]), []).append(t["speed_deg_s"])
    out["speed_by_step_deg"] = {k: round(statistics.median(v), 1) for k, v in sorted(by.items())}
    return out


def run_follow_cal(robot, make_grabber, find, steps=(10.0, 20.0, 30.0), repeats: int = 2, *, lift_deg: float = 120.0, pan_sign: str = "left", say=print, sleep=time.sleep,
                   clock=time.monotonic, stopped=lambda: False, exposure_lock: bool = False) -> dict:
    """Returns {"ended", "trials", "summary"}. Never raises; the caller lays him in rest."""
    from .. import focus
    from . import live_follow as lf
    res = {"ended": "error", "trials": [], "summary": {}}
    grab = None
    locked = False
    try:
        with focus.holding("follow_cal", "follow calibration"):
            if robot._tilt(1.5) is None:
                say("follow calibration: no IMU frames from the board: is the BiBoard powered on? Nothing was moved.")
                res["ended"] = "no_board"
                return res
            if robot.relax() == "fell" or robot._fell() or robot.claw_pose(0.0, lift_deg) == "fell":
                res["ended"] = "fell"
                return res
            sleep(0.8)
            base = robot._tilt()
            cfg = lf.LiveConfig()
            grab = make_grabber(find, cfg, clock, None)
            if exposure_lock and callable(getattr(grab, "set_exposure_lock", None)):
                locked = bool(grab.set_exposure_lock(True))
            grab.start()
            sleep(1.5)                                                       # the stream settles; the ball is seen at the centre
            res["ended"] = "done"
            pan = 0.0
            for rep in range(repeats):
                for mag in steps:
                    for direction in (+1, -1):
                        if stopped():
                            res["ended"] = "stopped"
                            return res
                        for to in (direction * mag, 0.0):                    # out, then back to the centre
                            ts = clock()
                            state = robot.claw_pose(to, lift_deg)
                            te = clock()
                            if state == "fell" or robot._fell():
                                res["ended"] = "fell"
                                return res
                            sleep(1.2)                                       # the pictures after the move arrive
                            rows = [(r["t_done"], r["det"][0][1] if r.get("det") else None) for r in list(grab.rows) if not r.get("bad")]
                            m = step_metrics(ts, te, pan, to, [x for x in rows if x[0] <= clock()], sign=pan_sign)
                            m.update(to=to, repeat=rep)
                            res["trials"].append(m)
                            say(f"step {m['step_deg']:+.0f} deg: command {m['command_s']} s, picture delay {m['delay_s']} s, speed {m['speed_deg_s']} deg/s")
                            pan = to
                            t = robot._tilt(0.3)
                            if base is not None and t is not None and max(abs(t[0] - base[0]), abs(t[1] - base[1])) > 8.0:
                                say("follow calibration: the body tilted: stopping")
                                res["ended"] = "tilt"
                                return res
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("g2.follow_cal").exception("the follow calibration failed")
        res["ended"] = "error"
    finally:
        if grab is not None:
            grab.stop_flag.set()
            try:
                grab.join(timeout=3.0)
            except Exception:  # noqa: BLE001
                pass
        if grab is not None and locked:
            try:
                grab.set_exposure_lock(False)                            # back to automatic exposure however the run ended
            except Exception:  # noqa: BLE001
                pass
        res["summary"] = summarize(res["trials"])
        res["summary"]["exposure_locked"] = locked
        res["summary"]["brightness"] = brightness_stats(list(getattr(grab, "rows", [])) if grab is not None else [])
        if res["trials"]:
            say(f"summary: {res['summary']}")
    return res


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Follow calibration: pan steps with a fixed ball in view; measures the picture delay and the pan speed. G2 moves: owner's go only.")
    ap.add_argument("--steps", default="10,20,30")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--lock-ae", action="store_true", help="freeze the sensor's auto exposure for the run (undone at the end)")
    args = ap.parse_args()
    from ..config import settings
    from ..link import imu_print
    from ..link.serial_link import SerialLink
    from ..power import battery
    from ..vision.snapshot import CameraSnapshotter
    from . import ball_chase as chase
    from . import live_follow as lf
    from .ball_tracker import BallTracker
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    if not imu_print.board_answers(link):
        print("refused: no IMU frames from the BiBoard: is it powered on? Nothing was moved.")
        return
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump)
    robot = chase.SerialRobot(link)
    stop_path = os.path.expanduser(STOP_FILE)
    if os.path.exists(stop_path):
        os.remove(stop_path)
    res = None
    try:
        chase._stand_if_lying(link, "kbalance")
        cam._open()
        res = run_follow_cal(robot, lambda f, c, clk, sv: lf.StreamGrabber(cam._ser, f, c, clock=clk, save=None), BallTracker(pan_sign=chase.CLAW_PAN_SIGN),
                             steps=tuple(float(s) for s in args.steps.split(",")), repeats=max(1, args.repeats), pan_sign=chase.CLAW_PAN_SIGN, stopped=lambda: os.path.exists(stop_path), exposure_lock=args.lock_ae)
        print(f"RESULT: {res['ended']}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        try:
            robot.claw_pose(0.0, 0.0)
        finally:
            cam.close()
            chase.ensure_rest(link)
    if res is not None:
        path = os.path.expanduser(time.strftime("~/g2_runs/followcal_%Y%m%d_%H%M%S.json"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(res, f, indent=1)
        print(f"SAVED: {path}")


if __name__ == "__main__":
    main()
