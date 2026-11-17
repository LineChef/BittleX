"""Turn calibration (hardware test, 2026-11-17): how well does the claw-equipped G2 turn in place? The ball goal lines the claw up with small gyro-stopped turns (`robot.turn(deg, s, stop_deg)`), and two of
the day's three falls began at the start of one. This runs the SAME call, no camera and no ball: G2 stands level, and for each asked size (default 6, 10 and 20 degrees) he turns right then left, twice. Each turn
logs the asked and the counted yaw, how long it ran and what ended it (the gyro, the cap, a stale yaw), and the body's pitch and roll through the move, so the overshoot (counted over asked), a turn that does
nothing and a roll at the start are all visible. Numbers only. A fall, a tilt of the body of more than the gate before a turn, or the stop file ends it; he is laid in rest at the end. Runs ONLY on the owner's go,
G2 standing on the floor, hands near, the voice service stopped (`g2turncal`).

    python -m pi_pipeline.behavior.turn_cal [--asks 6,10,20] [--repeats 2]
"""
from __future__ import annotations

import json
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
        out[f"asked_{ask:g}"] = {"n": len(ts), "got_median": round(statistics.median(t["got"] for t in ts), 1), "got_min": min(t["got"] for t in ts), "got_max": max(t["got"] for t in ts),
                                 "overshoot_median": round(statistics.median(ratios), 2), "roll_swing_max": max(t["roll_swing"] for t in ts), "ended_by": sorted({t["ended_by"] for t in ts})}
    out["fell"] = sum(1 for t in trials if t.get("state") == "fell")
    return out


def run_turn_cal(robot, asks=(6.0, 10.0, 20.0), repeats: int = 2, *, say=print, sleep=time.sleep, stopped=lambda: False, rate=lambda side: 45.0) -> dict:
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
                        res["trials"].append(t)
                        say(f"turn {t['dir']} asked {ask:g}: got {t['got']} deg in {t['ran_s']} s, ended by {t['ended_by']}, roll swing {t['roll_swing']}, pitch swing {t['pitch_swing']}, state {state}")
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
    robot = chase.SerialRobot(link)
    planner = chase.ChasePlanner()
    stop_path = os.path.expanduser(STOP_FILE)
    if os.path.exists(stop_path):
        os.remove(stop_path)
    res = None
    try:
        chase._stand_if_lying(link, "kbalance")
        res = run_turn_cal(robot, tuple(float(a) for a in args.asks.split(",")), max(1, args.repeats), stopped=lambda: os.path.exists(stop_path),
                           rate=lambda side: planner._turn_rate(side, False))
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
