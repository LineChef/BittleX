"""The post-punt watch as a hardware test (the owner's design, 2026-11-15): stand G2 up from rest, punt the ball (it is in range), watch it roll with the claw until it stops, take a picture, and
either say "target acquired" and go on with the normal chase (turn, walk, dial in the claw range, one more punt) or, if the ball is lost, turn toward the side it was last seen on and do the normal claw look.

`--no-punt` is the dry run: nothing is punted, the owner rolls the ball by hand while G2 stands and watches, and the test ends with the result (no chase afterwards).

Runs ONLY on the owner's go, G2 on the floor on his feet or in rest, hands near, the ball in punt range for the real run, the voice service stopped (`g2punttest`).

    python -m pi_pipeline.behavior.punt_watch_test [--no-punt]
"""
from __future__ import annotations

import json
import os
import sys
import time

from . import live_follow as lf
from .punt_watch import WatchConfig, WatchResult, watch_after_punt

STOP_FILE = "~/.local/share/g2/ball_chase_stop"


def result_line(r: WatchResult) -> str:
    side = {1: "right", -1: "left", 0: "unknown"}[r.last_side]
    return (f"WATCH: {r.ended}; found={r.found}; last seen {side}"
            + ("" if r.last_bearing is None else f" ({r.last_bearing:+.0f} deg)") + f"; {r.pictures} pictures, {r.moves} claw moves, {r.seconds:.1f} s"
            + ("" if r.reading is None else f"; ball {r.reading.distance_in:.0f} in, {r.reading.bearing_deg:+.0f} deg from straight ahead"))


def main() -> None:
    import argparse

    from ..config import settings
    from ..link import imu_print
    from ..link.serial_link import SerialLink
    from ..power import battery
    from ..vision.ball_finder import find_ball
    from ..vision.snapshot import CameraSnapshotter
    from . import ball_chase as chase
    from . import punt_settings as ps
    from .gallery_target import BallTarget
    ap = argparse.ArgumentParser(description="Punt, watch the ball roll with the claw, acquire it, and go on (or turn toward where it was last seen). Needs the owner's go.")
    ap.add_argument("--no-punt", action="store_true", help="dry run: no punt and no chase afterwards; roll the ball by hand")
    ap.add_argument("--seconds", type=float, default=WatchConfig.seconds, help="the longest the ball is followed")
    ap.add_argument("--turn", type=float, default=WatchConfig.lost_turn_deg, help="degrees to turn toward the last-seen side when the ball is lost")
    args = ap.parse_args()
    me = sys.modules[chase.__name__]
    _eff, problems = ps.effective(me)
    for p in problems:
        print("PUNT SETTINGS PROBLEM:", p)
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    if not imu_print.board_answers(link):
        print("refused: no IMU frames from the BiBoard: is it powered on? Nothing was moved.")
        return
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump, click=False)  # MODE-SPECIFIC(behavior/punt_watch_test.py, 2026-11-15): no shutter click in this look
    wrapped = chase._SnapshotCamera(cam)
    robot = chase.SerialRobot(link)
    tts = None
    try:
        from ..voice.tts import make_tts
        tts = make_tts("piper", piper_model_path=settings.piper_model_path, style=settings.voice_style)
    except Exception as e:  # noqa: BLE001
        print("no speech (", type(e).__name__, "): lines are printed only")

    def announce(text: str) -> None:
        print(f"G2: {text}")
        if tts is not None:
            import threading
            threading.Thread(target=tts.speak, args=(text,), daemon=True).start()
    outdir = os.path.expanduser(time.strftime("~/g2_claw_pics/watch_%Y%m%d_%H%M%S"))
    os.makedirs(outdir, exist_ok=True)

    def save(i, jpeg):
        with open(os.path.join(outdir, f"pic_{i:03d}.jpg"), "wb") as f:
            f.write(jpeg)
    target = BallTarget()
    cam._open()

    def make_grabber(find, cfg, clock, _save):
        return lf.StreamGrabber(cam._ser, find, cfg, clock=clock, save=save)

    def find_still(camera):
        jpeg = camera.look()
        return chase.confirm_ball(camera, find_ball(jpeg) if jpeg else None, time.sleep, None)

    def stop() -> bool:
        return os.path.exists(os.path.expanduser(STOP_FILE))
    try:
        os.remove(os.path.expanduser(STOP_FILE))
    except OSError:
        pass
    try:
        chase._stand_if_lying(link, "kbalance")
        if not args.no_punt:
            announce("punting")
            state = robot.punt()
            print("punt:", state)
            if state == "fell":
                return
        wcfg = WatchConfig(seconds=args.seconds, lost_turn_deg=args.turn)
        if args.no_punt:
            wcfg = WatchConfig(seconds=max(args.seconds, 25.0), never_seen_s=15.0, lost_turn_deg=args.turn)      # the dry run waits for you to roll the ball
        r = watch_after_punt(robot, wrapped, make_grabber, target.detections, find_still, wcfg, pan_sign=chase.CLAW_PAN_SIGN, announce=announce, stopped=stop,
                             on_ready=(lambda: announce("roll the ball now")) if args.no_punt else None)
        print(result_line(r))
        try:
            json.dump({"result": r.ended, "found": r.found, "last_side": r.last_side, "last_bearing": r.last_bearing, "pictures": r.pictures, "moves": r.moves, "seconds": r.seconds,
                       "rows": []}, open(os.path.join(outdir, "watch.json"), "w"))
        except OSError:
            pass
        print(f"PICTURES: {outdir}")
        if args.no_punt or r.ended in ("fell", "sag", "stopped_by_user", "no_board", "error"):
            return
        planner = chase.ChasePlanner()
        if not r.found and r.last_side:
            side = r.last_side
            robot.claw_pose(0.0, 0.0)
            deg = side * args.turn
            announce(f"turning {'right' if side > 0 else 'left'}")
            robot.turn(deg, abs(deg) / planner._turn_rate(side, False), stop_deg=abs(deg))
        if not r.found:
            planner.lost = chase.LOST_LOOKS - 1                   # the first empty picture starts the normal search (the claw look)
        why = chase.run_chase(robot, wrapped, stop, planner=planner, announce=announce, say=print, max_punts=1, max_seconds=60.0, pace=chase._book(),
                              first_reading=r.reading if r.found else None)
        print("CHASE ended:", why)
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
