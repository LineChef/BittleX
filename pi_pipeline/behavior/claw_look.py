"""The claw look (goals plan, 2026-10-31): G2 points the camera with the arm (it is mounted on the claw) to look for the ball without moving his legs.

The move itself is `ball_chase.SerialRobot.claw_pose` (arm pan = joint 0, lift = joint 1, at 60 deg/s, the IMU watched) and the look around is `ball_chase.claw_scan`. This module is the
hardware check for both:

    python -m pi_pipeline.behavior.claw_look --calibrate   # the ball about 12 in straight ahead: measures which way a positive pan turns the camera and saves it (claw_pan_sign)
    python -m pi_pipeline.behavior.claw_look --test        # one look around with the current settings; says where it saw the ball

On the Pi with the voice service stopped, G2 standing on the floor (he is stood up if lying), hands near. Every picture keeps exposure balancing on. He rests at the end.
"""
from __future__ import annotations

import time

from ..vision.ball_finder import find_ball

CAL_PAN_DEG = 20.0             # small: the ball stays in view at about 12 in


def pan_sign_from(bearing_at_0: float, bearing_at_plus: float, pan: float = CAL_PAN_DEG) -> str | None:
    """Which way a positive pan turns the camera, from the ball's bearing in the picture at pan 0 and at pan +`pan`. The camera turning right makes the ball appear further LEFT
    (a smaller bearing). None when the shift is too small to tell (under a third of the pan)."""
    shift = bearing_at_plus - bearing_at_0
    if abs(shift) < pan / 3.0:
        return None
    return "right" if shift < 0 else "left"


def calibrate(robot, camera, *, say=print, sleep=time.sleep) -> str | None:
    """Pan 0, then +CAL_PAN_DEG, a picture at each; back to 0. Returns "right", "left" or None (the ball was not seen in both, or the shift was too small)."""
    readings = {}
    for pan in (0.0, CAL_PAN_DEG):
        if robot.claw_pose(pan, 0.0) == "fell":
            say("G2 fell: stopping")
            return None
        sleep(0.8)
        jpeg = camera.look()
        ball = find_ball(jpeg) if jpeg else None
        say(f"pan {pan:+.0f}: " + (f"ball {ball.distance_in:.0f} in, {ball.bearing_deg:+.1f} deg in the picture" if ball else "no ball"))
        readings[pan] = ball
    robot.claw_pose(0.0, 0.0)
    if readings[0.0] is None or readings[CAL_PAN_DEG] is None:
        say("the ball was not seen in both pictures: put it about 12 in straight ahead and try again")
        return None
    sign = pan_sign_from(readings[0.0].bearing_deg, readings[CAL_PAN_DEG].bearing_deg)
    say(f"a positive pan turns the camera to the {sign}" if sign else "the ball hardly moved in the picture: is the arm moving? try again")
    return sign


def hold_test(link, *, seconds: float = 20.0, say=print, sleep=time.sleep, clock=time.monotonic, sag_deg: float = 8.0) -> dict:
    """Stand still and watch (no arm move, no picture): the IMU pitch and roll every 0.25 s and the pack voltage every 2 s for `seconds`, to see whether the legs relax by
    themselves and when (2026-11-01: his legs let go about 10 s after the stand-up). A sag shows as pitch or roll moving more than `sag_deg` from where he stood in the
    first 2 s. Returns {"sag_at_s": seconds or None, "min_volts": ..., "max_dev_deg": ...}. Moves nothing."""
    import math
    import statistics

    from ..gait.imu_parse import parse_imu_line
    from ..power import battery
    link.send("gP", read_reply=False, settle=0.0)
    t0 = clock()
    pitch, roll = [], []
    base = None
    sag_at, max_dev, min_v, next_v, last_print = None, 0.0, None, 0.0, -1.0
    try:
        while clock() - t0 < seconds:
            t = clock() - t0
            for line in link.poll_imu():
                r = parse_imu_line(line)
                if r is not None:
                    roll.append(math.degrees(r[0]))
                    pitch.append(math.degrees(r[1]))
            if base is None and t >= 2.0 and pitch:
                base = (statistics.median(pitch), statistics.median(roll))
                say(f"standing baseline: pitch {base[0]:+.1f} roll {base[1]:+.1f} deg")
            if base is not None and pitch:
                dev = max(abs(pitch[-1] - base[0]), abs(roll[-1] - base[1]))
                max_dev = max(max_dev, dev)
                if sag_at is None and dev > sag_deg:
                    sag_at = round(t, 1)
                    say(f"  {t:4.1f} s: the body moved {dev:.0f} deg from where he stood (pitch {pitch[-1]:+.1f}, roll {roll[-1]:+.1f}): the legs gave way")
            if t >= next_v:
                v = battery.read_voltage(link, attempts=1)
                next_v = t + 2.0
                if v is not None:
                    min_v = v if min_v is None else min(min_v, v)
            if int(t) != last_print and pitch:
                last_print = int(t)
                say(f"  {t:4.1f} s: pitch {pitch[-1]:+.1f} roll {roll[-1]:+.1f}" + (f"  pack {min_v:.2f} V (lowest so far)" if min_v is not None else ""))
            sleep(0.25)
    finally:
        link.send("gp", read_reply=False, settle=0.0)
    say(f"hold test done: " + (f"the legs gave way at {sag_at} s" if sag_at is not None else f"he held for {seconds:.0f} s (largest body movement {max_dev:.1f} deg)") + (f"; lowest pack {min_v:.2f} V" if min_v is not None else ""))
    return {"sag_at_s": sag_at, "min_volts": min_v, "max_dev_deg": round(max_dev, 1)}


def take_pictures(robot, camera, outdir: str, *, pan: float, lift: float, say=print, sleep=time.sleep, settle_s: float = 1.2) -> list:
    """Three pictures from the claw camera, in this order: straight ahead (pan 0), then pan +`pan`, then pan -`pan`, all at `lift`; then the arm goes home. Each is saved as
    straight.jpg / pan_plus.jpg / pan_minus.jpg in `outdir`. After each move it says how far the body tilted during it (`robot.swing_deg()`): a big number means the arm move leans him.
    Stops at once on a fall. Returns [(name, pan, swing_deg, path or None)]."""
    import os
    os.makedirs(outdir, exist_ok=True)
    out = []
    fresh = getattr(camera, "refresh_exposure", None)
    if callable(fresh):
        fresh()                                                                      # one exposure check before the whole move (user, 2026-10-31), not one per picture
    for name, p in (("straight", 0.0), ("pan_plus", pan), ("pan_minus", -pan)):
        state = robot.claw_pose(p, lift)
        swing = robot.swing_deg() if hasattr(robot, "swing_deg") else 0.0
        if state == "fell":
            say(f"{name}: G2 fell during the move: stopping")
            out.append((name, p, swing, None))
            return out
        sleep(settle_s)
        jpeg = camera.look()
        path = None
        if jpeg:
            path = os.path.join(outdir, f"{name}.jpg")
            with open(path, "wb") as f:
                f.write(jpeg)
        say(f"{name}: pan {p:+.0f} lift {lift:.0f}: body tilted {swing:.1f} deg during the move; " + (f"picture saved to {path}" if path else "no picture from the camera"))
        out.append((name, p, swing, path))
    robot.claw_pose(0.0, 0.0)
    return out


def main() -> None:
    import argparse
    import sys

    from . import ball_chase as chase
    from . import punt_settings as ps
    ap = argparse.ArgumentParser(description="Check the claw look on G2.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--calibrate", action="store_true", help="measure which way a positive pan turns the camera and save it (the ball about 12 in straight ahead)")
    g.add_argument("--test", action="store_true", help="one look around with the current settings")
    ap.add_argument("--gb", action="store_true", help="with --hold: send `gb` (firmware gyro balance off) right after the stand-up, before watching")
    g.add_argument("--hold", action="store_true", help="stand, then do nothing for 20 s and watch whether the legs hold (IMU and pack voltage); no arm move")
    g.add_argument("--pictures", action="store_true", help="three pictures (straight, pan +, pan -) saved to a folder; stays standing at the end (no rest command)")
    ap.add_argument("--rest", action="store_true", help="with --pictures: lay him down at the end like the other modes")
    args = ap.parse_args()
    me = sys.modules[chase.__name__]
    _eff, problems = ps.effective(me)
    for p in problems:
        print("PUNT SETTINGS PROBLEM:", p)
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
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump)       # exposure balancing stays on
    robot = chase.SerialRobot(link)
    try:
        chase._stand_if_lying(link)
        if args.hold:
            if args.gb:
                link.send("gb", read_reply=False, settle=0.0)
                print("sent gb (firmware gyro balance off) after the stand-up")
            hold_test(link)
        elif args.pictures:
            import os
            outdir = os.path.expanduser(time.strftime("~/g2_claw_pics/%Y%m%d_%H%M%S"))
            res = take_pictures(robot, chase._SnapshotCamera(cam), outdir, pan=chase.CLAW_PAN_DEG, lift=chase.CLAW_LIFT_DEG)
            print("PICTURES:", outdir, [r[0] for r in res if r[3]])
        elif args.calibrate:
            sign = calibrate(robot, chase._SnapshotCamera(cam))
            if sign:
                print("saved:", ps.set_value(me, "claw_pan_sign", sign))
        else:
            state, ball = chase.claw_scan(robot, chase._SnapshotCamera(cam), chase.ChasePlanner())
            print("ended:", state, "-", f"ball {ball.distance_in:.0f} in, {ball.bearing_deg:+.0f} deg from straight ahead" if ball else "no ball seen")
    except KeyboardInterrupt:
        print("ended")
    finally:
        try:
            robot.claw_pose(0.0, 0.0)
        finally:
            cam.close()
            if not (args.pictures or args.hold) or args.rest:
                link.send("krest", read_reply=False, settle=0.0)
                time.sleep(2.5)
            else:
                print("no rest command sent: left as he is; arm home")


if __name__ == "__main__":
    main()
