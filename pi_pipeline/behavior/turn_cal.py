"""Turn calibration (hardware test, 2026-11-17): how well does the claw-equipped G2 turn (the firmware turn gaits are ARC turns that step forward, not a pivot)? The ball goal lines the claw up with small gyro-stopped turns (`robot.turn(deg, s, stop_deg)`), and two of
the day's three falls began at the start of one. This runs the SAME call, no camera and no ball: G2 stands level, and for each asked size (default 6, 10 and 20 degrees) he turns right then left, twice. Each turn
logs the asked and the counted yaw, how long it ran and what ended it (the gyro, the cap, a stale yaw), and the body's pitch and roll through the move, so the overshoot (counted over asked), a turn that does
nothing and a roll at the start are all visible. Numbers only. A fall, a tilt of the body of more than the gate before a turn, or the stop file ends it; he is laid in rest at the end. Runs ONLY on the owner's go,
G2 standing on the floor, hands near, the voice service stopped (`g2turncal`).

    python -m pi_pipeline.behavior.turn_cal [--asks 6,10,20] [--repeats 2]
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time

STOP_FILE = "~/.local/share/g2/turncal_stop"
SETTLE_S = 2.0


def summarize(trials: list) -> dict:
    out = {}
    for ask in sorted({t["asked"] for t in trials}):
        ts = [t for t in trials if t["asked"] == ask and t.get("got") is not None]
        if not ts:
            continue
        ratios = [t["got"] / t["asked"] for t in ts]
        fw = [t["fwd_in"] for t in ts if t.get("fwd_in") is not None]
        out[f"asked_{ask:g}"] = {"fwd_in_median": round(statistics.median(fw), 1) if fw else None, "n": len(ts), "got_median": round(statistics.median(t["got"] for t in ts), 1), "got_min": min(t["got"] for t in ts), "got_max": max(t["got"] for t in ts),
                                 "overshoot_median": round(statistics.median(ratios), 2), "roll_swing_max": max(t["roll_swing"] for t in ts), "ended_by": sorted({t["ended_by"] for t in ts})}
    out["fell"] = sum(1 for t in trials if t.get("state") == "fell")
    return out


def _xy(ball):
    """(forward inches, sideways inches) of a ball reading, or None."""
    if ball is None:
        return None
    a = math.radians(ball.bearing_deg)
    return ball.distance_in * math.cos(a), ball.distance_in * math.sin(a)


def run_turn_cal(robot, asks=(6.0, 10.0, 20.0), repeats: int = 2, *, say=print, sleep=time.sleep, stopped=lambda: False, rate=lambda side: 45.0, look=None) -> dict:
    """Returns {"ended", "trials", "summary"}. Never raises; the caller lays him in rest."""
    from .. import focus
    res = {"ended": "error", "trials": [], "summary": {}}
    try:
        with focus.holding("turn_cal", "turn calibration"):
            if robot._tilt(1.5) is None:
                say("turn calibration: no IMU frames from the board: is the BiBoard powered on? Nothing was moved.")
                res["ended"] = "no_board"
                return res
            res["ended"] = "done"
            seen = _xy(look()) if look is not None else None                       # where the ball is now (a fixed ball ahead: how far each turn moves him forward)
            for rep in range(repeats):
                for ask in asks:
                    for sign in (+1, -1):
                        if stopped():
                            res["ended"] = "stopped"
                            return res
                        side = 1 if sign > 0 else -1
                        before = robot._tilt(0.3)
                        secs = max(0.3, ask / rate(side))
                        state = robot.turn(sign * ask, secs, stop_deg=ask)
                        roll, pitch = list(getattr(robot, "_roll", []) or []), list(getattr(robot, "_pitch", []) or [])
                        t = {"asked": ask, "dir": "right" if sign > 0 else "left", "state": state, "got": getattr(robot, "last_turn_deg", None), "ran_s": getattr(robot, "last_turn_s", None),
                             "ended_by": getattr(robot, "last_turn_end", None), "tilt_before": [round(x, 1) for x in before] if before else None,
                             "roll_swing": round(max(roll) - min(roll), 1) if roll else 0.0, "pitch_swing": round(max(pitch) - min(pitch), 1) if pitch else 0.0}
                        if look is not None:
                            sleep(SETTLE_S)
                            after = _xy(look())
                            if seen is not None and after is not None:
                                t["fwd_in"] = round(seen[0] - after[0], 1)               # the ball got this much closer straight ahead = he moved forward this far
                                t["side_in"] = round(after[1] - seen[1], 1)
                            seen = after
                        res["trials"].append(t)
                        say(f"turn {t['dir']} asked {ask:g}: got {t['got']} deg in {t['ran_s']} s, ended by {t['ended_by']}, roll swing {t['roll_swing']}, pitch swing {t['pitch_swing']}, forward {t.get('fwd_in')} in, state {state}")
                        if state == "fell" or robot._fell():
                            res["ended"] = "fell"
                            return res
                        sleep(SETTLE_S)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("g2.turn_cal").exception("the turn calibration failed")
        res["ended"] = "error"
    finally:
        res["summary"] = summarize(res["trials"])
        if res["trials"]:
            say(f"summary: {res['summary']}")
    return res


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Turn calibration: the ball goal's gyro-stopped small turns, right and left, with the log of asked against counted yaw and the tilt. G2 moves: owner's go only.")
    ap.add_argument("--asks", default="6,10,20")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--token", choices=("wk", "vt", "cr", "tr"), default="wk", help="the skill family to turn with: wk = kwkL/kwkR (the chase's), vt = kvtL/kvtR (a candidate pivot), cr, tr")
    ap.add_argument("--cap", type=float, default=0.0, help="the longest one turn may run, in seconds, for this calibration only (0 = the ball goal's own cap, ALIGN_CAP_S): longer pivots show whether a turn stays in place")
    ap.add_argument("--ball", action="store_true", help="a ball fixed 14 to 20 in straight ahead: the camera measures how far each turn moves him forward")
    args = ap.parse_args()
    from ..link import imu_print
    from ..link.serial_link import SerialLink
    from ..power import battery
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
    if args.cap > 0:
        chase.ALIGN_CAP_S = min(float(args.cap), 6.0)                 # this process only; never above the 6 s turn limit
    robot = chase.SerialRobot(link)
    robot.turn_tokens = (f"k{args.token}R", f"k{args.token}L")
    planner = chase.ChasePlanner()
    stop_path = os.path.expanduser(STOP_FILE)
    if os.path.exists(stop_path):
        os.remove(stop_path)
    res = None
    try:
        chase._stand_if_lying(link, "kbalance")
        look = None
        if args.ball:
            from ..config import settings
            from ..vision.ball_finder import find_ball
            from ..vision.snapshot import CameraSnapshotter
            cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump)
            shot = chase._SnapshotCamera(cam)

            def look():
                for _ in range(3):
                    shot.refresh_exposure()
                    jpeg = shot.look()
                    ball = chase.confirm_ball(shot, find_ball(jpeg) if jpeg else None, time.sleep, None)
                    if ball is not None:
                        return ball
                    time.sleep(0.5)
                return None
        res = run_turn_cal(robot, tuple(float(a) for a in args.asks.split(",")), max(1, args.repeats), stopped=lambda: os.path.exists(stop_path),
                           rate=lambda side: planner._turn_rate(side, False), look=look)
        print(f"RESULT: {res['ended']}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        chase.ensure_rest(link)
    if res is not None:
        path = os.path.expanduser(time.strftime("~/g2_runs/turncal_%Y%m%d_%H%M%S.json"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(res, f, indent=1)
        print(f"SAVED: {path}")


if __name__ == "__main__":
    main()
