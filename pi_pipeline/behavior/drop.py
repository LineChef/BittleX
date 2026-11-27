"""The drop: G2 lets go of the puck he holds, as one shared move (owner, 2026-11-27: "call the new move drop and make it open, then close the claw").

Raise the arm to the claw look's height first (the claw touches the floor in the carry position and opening it there drags it: the owner saw this on 2026-11-20, so no jaw command is ever sent with the arm down), open the jaw (0 is closed,
positive opens; 0 to 60 was driven on G2 by `g2jawrange`), hold it open long enough for the puck to fall, close it, then lower the arm. Standing the whole time; the legs stay as they are. Every way in calls `drop_puck`: the pick-up drill
(`goals/pickup.py` through `RealEnv.drop`) and the `g2drop` test tool (`python -m pi_pipeline.behavior.drop`, which picks a puck up first, then drops it). Not yet run on G2: the numbers below are the ones `g2jawrange` showed
working for the jaw and the claw look's lift height; the open time is the first guess to tune by eye.
"""
from __future__ import annotations

import time

DROP_LIFT_DEG = 120.0        # the claw look's height: the claw is clear of the floor (the jaw sweep tool raises the arm the same way)
DROP_JAW_OPEN_DEG = 60.0     # the widest the jaw was driven (a puck is about as wide as the jaw's opening at less)
DROP_OPEN_S = 0.8            # the jaw stays open this long so the puck falls out
DROP_CLOSE_S = 0.4           # and this long closed before the arm comes down


def drop_puck(robot, say=print, sleep=time.sleep, *, lift: float = DROP_LIFT_DEG, jaw_open: float = DROP_JAW_OPEN_DEG, open_s: float = DROP_OPEN_S, close_s: float = DROP_CLOSE_S,
              read_arm=None, info: dict | None = None, clock=time.monotonic) -> str:
    """Raise the arm, open then close the jaw, lower the arm. "ok" or "fell". `robot` is the `SerialRobot` (claw_pose, _tx). Never sends the jaw anything with the arm down.
    For dialing it in, `info` collects: `commands` (the jaw commands sent), `arm_reads` (`read_arm()` returns the board's [pan, lift, jaw]: the angles it was last told to hold, so a command it ignored shows as no change; read before
    the open, while open and after the close), `phases` (seconds each took) and `tilt_max_deg` (the worst pitch and roll the IMU saw during the two arm moves). All are said as well. 2026-11-27 run: the claw never opened and nothing recorded why."""
    info = info if info is not None else {}
    info.update(commands=[], arm_reads=[], phases=[], tilt_max_deg=[])
    t0 = clock()

    def phase(label):
        info["phases"].append([label, round(clock() - t0, 2)])

    def tilt():
        try:
            info["tilt_max_deg"].append([round(max((abs(x) for x in list(robot._pitch)), default=0.0), 1), round(max((abs(x) for x in list(robot._roll)), default=0.0), 1)])
        except Exception:  # noqa: BLE001
            info["tilt_max_deg"].append(None)

    def note(label):
        if read_arm is None:
            return
        try:
            v = read_arm()
        except Exception:  # noqa: BLE001
            v = None
        info["arm_reads"].append([label, v])
        say(f"drop: arm reads (pan, lift, jaw) {v} {label}")

    def jaw(angle):
        c = f"i2 {int(round(angle))}"
        info["commands"].append(c)
        robot._tx(c)
    say(f"drop: raising the arm to {lift:g}")
    if robot.claw_pose(0.0, lift) == "fell":
        return "fell"
    phase("raised")
    tilt()
    note("before opening")
    say(f"drop: opening the claw to {jaw_open:g}")
    jaw(jaw_open)
    sleep(open_s)
    phase("jaw open")
    note("while open")
    jaw(0)
    say("drop: closing the claw")
    sleep(close_s)
    phase("jaw closed")
    note("after closing")
    if robot.claw_pose(0.0, 0.0) == "fell":                  # the arm comes down only after the jaw is closed again
        return "fell"
    phase("lowered")
    tilt()
    note("arm down")
    return "ok"


def main(argv: list | None = None) -> None:
    import argparse

    from . import ball_chase as chase
    from . import catapult
    ap = argparse.ArgumentParser(description="The drop test: stand him up, pick the puck up from in front of the claw, drop it, rest. The person's go first; hands near; the voice service stopped (g2drop).")
    ap.add_argument("--no-pick", action="store_true", help="drop only (the puck is already in the claw)")
    args = ap.parse_args(argv)
    from ..link import imu_print
    from ..link.serial_link import SerialLink
    from ..power import battery
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    if not imu_print.board_answers(link):
        print("refused: no IMU frames from the BiBoard: is it powered on? Nothing was sent.")
        return
    robot = chase.SerialRobot(link)
    try:
        chase._stand_if_lying(link, "kbalance")
        if not args.no_pick:
            print("picking the puck up (pickF)")
            catapult.pick_up(link, seen=[])
            time.sleep(0.5)
        def read_arm():
            joints = chase.read_joints(link)
            return None if not joints or len(joints) < 3 else list(joints[:3])
        info: dict = {}
        print("drop:", drop_puck(robot, read_arm=read_arm, info=info))
        print("drop log:", info)
    except KeyboardInterrupt:
        print("ended")
    finally:
        chase.ensure_rest(link)


if __name__ == "__main__":
    main()
