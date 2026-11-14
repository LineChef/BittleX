"""Survey poses one at a time (2026-11-10): which of the survey stop's poses tips G2 over? Runs ONLY on the user's go, on hardwood, hands near, the voice service stopped (behavior/service_off.sh).

A survey stop is: sit (look up), bow (`kbuttUp`, look down), stand, the `kck` lean, stand. Here each pose is played on its own from a standing G2, held while the IMU tilt is logged, then G2 is stood up the eased
way (`_stand_if_lying`: the pose is read and the K stand-up played), so a fall can be pinned on one pose. Stops at the first fall or at a tilt swing of FELL_SWING_DEG, and always ends in the rest position.

    python -m pi_pipeline.behavior.survey_pose_test [--poses ksit,kbuttUp,kck] [--rounds 2]
"""
from __future__ import annotations

import time

POSES = {"ksit": ("sit (look up)", 2.5), "kbuttUp": ("bow (look down)", 2.5), "kck": ("check lean", 4.8)}      # token -> (name, seconds held: kck needs 4.6 s to finish, measured 2026-10-18)
FELL_SWING_DEG = 30.0           # a tilt swing this big in a pose counts as a fall even when the fall limit was not reached (same as the transition drill)
MIN_PACK_PCT = 30


def play_pose(robot, link, token: str, hold_s: float, *, say=print, sleep=time.sleep, clock=time.monotonic) -> dict:
    """One pose from a stand: sent, held `hold_s` while the tilt is read, ended by the caller's stand-up. Returns {"fell", "swing_deg", "pitch", "roll"}."""
    robot._pitch, robot._roll = [], []
    robot._tx("gP")                                   # the IMU stream on for the pose
    sleep(0.3)
    robot._fell()
    robot._pitch, robot._roll = [], []
    link.send(token, read_reply=False, settle=0.0)    # the link eases into the skill from the known pose (link/transitions.py)
    t0, fell = clock(), False
    while clock() - t0 < hold_s:
        if robot._fell():
            fell = True
            break
        sleep(0.05)
    swing = robot.swing_deg()
    p, r = list(robot._pitch), list(robot._roll)
    robot._tx("gp")
    if swing >= FELL_SWING_DEG:
        fell = True
    return {"fell": fell, "swing_deg": round(swing, 1), "pitch": (round(min(p)), round(max(p))) if p else None, "roll": (round(min(r)), round(max(r))) if r else None, "frames": len(p)}


def run(robot, link, poses: list[str], rounds: int, *, say=print, sleep=time.sleep) -> dict:
    from . import ball_chase as chase
    results, fell_at = [], ""
    for rnd in range(1, rounds + 1):
        for token in poses:
            name, hold = POSES[token]
            if not chase._stand_if_lying(link, "kbalance") and robot.fallen():       # stands him up the eased way if he is not standing
                return {"results": results, "fell_at": f"before {name}", "rounds": rnd}
            sleep(2.0)                                                                  # the stance settles before the pose
            res = play_pose(robot, link, token, hold, say=say, sleep=sleep)
            res.update(round=rnd, pose=token)
            results.append(res)
            say(f"round {rnd} {name}: swing {res['swing_deg']} deg, pitch {res['pitch']}, roll {res['roll']}, {res['frames']} IMU frames" + (" FELL" if res["fell"] else ""))
            if res["fell"]:
                return {"results": results, "fell_at": name, "rounds": rnd}
            chase._stand_if_lying(link, "kbalance")                                     # the pose read says what he is in; the stand-up is the eased one
            say(f"   stand-up after the {name}: swing {robot.swing_deg():.0f} deg")
            if robot.swing_deg() >= FELL_SWING_DEG:
                return {"results": results, "fell_at": f"stand-up after {name}", "rounds": rnd}
    return {"results": results, "fell_at": fell_at, "rounds": rounds}


def main() -> None:
    import argparse
    import subprocess

    from . import ball_chase as chase
    ap = argparse.ArgumentParser(description="Survey poses one at a time: which one tips G2 over?")
    ap.add_argument("--poses", default=",".join(POSES), help="comma-separated skill tokens, in order (default: ksit,kbuttUp,kck)")
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()
    poses = [p for p in args.poses.split(",") if p]
    bad = [p for p in poses if p not in POSES]
    if bad:
        ap.error(f"unknown pose(s) {bad}: choose from {sorted(POSES)}")
    try:
        up = subprocess.run(["systemctl", "is-active", "g2-voice"], capture_output=True, text=True, timeout=5).stdout.strip() == "active"
    except Exception:  # noqa: BLE001
        up = False
    if up:
        print("the g2-voice service is RUNNING: it shares the BiBoard's serial port. Stop it the safe way first (pi_pipeline/behavior/service_off.sh). Round not run.")
        return
    from ..link.serial_link import SerialLink
    from ..power import battery
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link, min_percent=MIN_PACK_PCT)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    robot = chase.SerialRobot(link)
    try:
        if not robot.imu_alive():
            print("NO IMU FRAMES: the board is silent, a fall would not be seen. Check the Pi-to-BiBoard plug. Not run.")
            return
        res = run(robot, link, poses, args.rounds)
        print("RESULT", res)
    except KeyboardInterrupt:
        print("ended")
    finally:
        try:                                            # always laid in the rest position at the end, a fall included (owner, 2026-11-08)
            from .ball_chase import ensure_rest
            ensure_rest(link)
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
