"""Lift calibration (hardware test, 2026-11-15): how far the picture moves up and down per degree of claw lift, and how far the lift can safely go.

The live follow turns the claw left and right only. To follow a target up and down the lift joint (index 1) would tilt the camera, but nobody has measured which way and how much, and the claw look raises
the lift to 120 first because from a low lift the claw sits between the front legs. This test holds the pan at 0 with a ball fixed in view and steps the lift down from 120 in small steps. At each step it
takes two pictures (the first is dropped: the module answers with the previous request's picture), finds the ball with the colour finder, and reads the body's tilt. It stops at the first step that tilts
the body `MAX_TILT_DEG` from where it stood, or that falls (a ball that leaves the frame does not stop it: the whole scene is measured on the saved pictures), then puts the claw down and stands him up the standard way.

The table it prints: lift, the ball's centre (x, y) and diameter in frame fractions, the tilt from the starting stand, and the camera's vertical shift per degree of lift (the vertical field of view is
taken as the horizontal one, 89 deg over the square frame). Runs ONLY on the owner's go, G2 on the floor, hands near, the voice service stopped (`g2liftcal`).

    python -m pi_pipeline.behavior.lift_cal
"""
from __future__ import annotations

import os
import time

LIFTS = (120.0, 105.0, 90.0, 75.0, 60.0, 45.0, 30.0)
MAX_LOST = 99                       # the ball may leave the frame as the view tilts: keep stepping, the pictures are measured on the whole scene afterwards
MAX_TILT_DEG = 6.0
FOV_DEG = 89.0                  # the measured full field of view (pan fit, 2026-11-15); the vertical one is assumed equal for the square frame


def shift_per_degree(rows: list[dict]) -> list[dict]:
    """For each step after the first with the ball in both pictures: the picture's vertical shift per degree of lift (degrees of view per degree of lift; + = the ball moved down in the picture as the lift went down)."""
    out = []
    for a, b in zip(rows, rows[1:]):
        if a.get("cy") is None or b.get("cy") is None:
            continue
        dl = a["lift"] - b["lift"]
        if dl == 0:
            continue
        out.append({"from": a["lift"], "to": b["lift"], "view_deg_per_lift_deg": round((b["cy"] - a["cy"]) * FOV_DEG / dl, 2)})
    return out


def run_lift_cal(robot, look, lifts=LIFTS, *, say=print, sleep=time.sleep, stopped=lambda: False) -> dict:
    """`look()` -> (cx, cy, w, h) of the ball in frame fractions, or None. Returns {"ended", "rows", "shift"}. Never raises; the claw is lowered and G2 stands up the standard way at the end."""
    from .. import focus
    res = {"ended": "error", "rows": [], "shift": []}
    try:
        with focus.holding("lift_cal", "lift calibration"):
            if robot._tilt(1.5) is None:
                say("lift calibration: no IMU frames from the board: is the BiBoard powered on? Nothing was moved.")
                res["ended"] = "no_board"
                return res
            if robot.relax() == "fell" or robot._fell():
                res["ended"] = "fell"
                return res
            if robot.claw_pose(0.0, lifts[0]) == "fell":
                res["ended"] = "fell"
                return res
            sleep(1.2)
            base = robot._tilt()
            res["ended"] = "done"
            lost = 0
            for lift in lifts:
                if stopped():
                    res["ended"] = "stopped"
                    break
                if robot.claw_pose(0.0, lift) == "fell":
                    res["ended"] = "fell"
                    break
                sleep(1.2)
                look()                                                   # the module answers with the previous request's picture: drop one
                sleep(0.8)
                b = look()
                t = robot._tilt()
                dev = None if (base is None or t is None) else round(max(abs(t[0] - base[0]), abs(t[1] - base[1])), 1)
                row = {"lift": lift, "cx": None if b is None else round(b[0], 3), "cy": None if b is None else round(b[1], 3), "diameter": None if b is None else round(b[2], 3), "tilt_dev": dev}
                res["rows"].append(row)
                say(f"lift {lift:.0f}: ball {'not seen' if b is None else f'x={b[0]:.2f} y={b[1]:.2f} size={b[2]:.2f}'}, body tilt {dev if dev is not None else '?'} deg from the stand")
                lost = lost + 1 if b is None else 0
                if dev is not None and dev >= MAX_TILT_DEG:
                    say(f"lift calibration: the body tilted {dev} deg at lift {lift:.0f}: stopping here")
                    res["ended"] = "tilt"
                    break
                if lost >= MAX_LOST:
                    say("lift calibration: the ball is out of view: stopping here")
                    res["ended"] = "lost"
                    break
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("g2.lift_cal").exception("the lift calibration failed")
        res["ended"] = "error"
    finally:
        try:
            if res["ended"] not in ("fell", "no_board"):
                robot.claw_pose(0.0, 0.0)
                robot.stand_up()
        except Exception:  # noqa: BLE001
            pass
    res["shift"] = shift_per_degree(res["rows"])
    for s in res["shift"]:
        say(f"lift {s['from']:.0f} -> {s['to']:.0f}: the picture moves {s['view_deg_per_lift_deg']:+.2f} deg of view per degree of lift (+ = the ball moves down in the picture)")
    return res


def main() -> None:
    from ..config import settings
    from ..link import imu_print
    from ..link.serial_link import SerialLink
    from ..power import battery
    from ..vision.ball_finder import find_ball
    from ..vision.snapshot import CameraSnapshotter
    from . import ball_chase as chase
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    if not imu_print.board_answers(link):
        print("refused: no IMU frames from the BiBoard: is it powered on? Nothing was moved.")
        return
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump, click=False)  # MODE-SPECIFIC(behavior/lift_cal.py, 2026-11-15): no shutter click in this look
    robot = chase.SerialRobot(link)
    outdir = os.path.expanduser(time.strftime("~/g2_claw_pics/liftcal_%Y%m%d_%H%M%S"))
    os.makedirs(outdir, exist_ok=True)
    n = {"i": 0}

    def look():
        snap = cam.snapshot()
        if snap is None:
            return None
        n["i"] += 1
        try:
            with open(os.path.join(outdir, f"pic_{n['i']:02d}.jpg"), "wb") as f:
                f.write(snap.jpeg)
        except OSError:
            pass
        b = find_ball(snap.jpeg)
        return None if b is None else (b.x / 240.0, b.y / 240.0, b.width / 240.0, b.height / 240.0)
    try:
        chase._stand_if_lying(link, "kbalance")
        res = run_lift_cal(robot, look)
        print(f"RESULT: {res['ended']}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        try:
            robot.claw_pose(0.0, 0.0)
        finally:
            cam.close()
            from .ball_chase import ensure_rest
            ensure_rest(link)
    print(f"PICTURES: {outdir}")


if __name__ == "__main__":
    main()
