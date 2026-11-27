"""The drop: G2 lets go of the puck he holds, as one shared move (owner, 2026-11-27: "call the new move drop and make it open, then close the claw").

He stays standing. The arm goes up first (the claw touches the floor in the carry position and opening it there drags it: the owner saw this on 2026-11-20, so no jaw command is ever sent with the arm down), the jaw opens (0 is
closed, positive opens; 0 to 60 was driven on G2 by `g2jawrange`), stays open long enough for the puck to fall, and closes. By default the arm then comes down; the pick-up drill (`goals/pickup.py` through `RealEnv.drop`) passes
`lower=False`: the puck lies under the claw, so he backs up with the arm still raised and lowers it afterwards (owner, 2026-11-27: lowering the claw onto the puck, then lying down and standing, lifted the claw and flipped him every
time). The `g2drop` test tool picks a puck up first, then drops it. Not yet run on G2 at the standing lift below: 120 pitched a standing body about 18 degrees (the move gate's limit is 12), the attention pose (`attention=True`) stayed
within 3 degrees but cannot walk back, so DROP_LIFT_DEG is a first guess to tune by eye (the jaw must clear the floor) and the tilt log.
"""
from __future__ import annotations

import time

DROP_LIFT_DEG = 75.0         # standing: low enough that the body does not pitch past the move gate (about 0.15 degrees of pitch per degree of lift: 120 read 18, so about 11 here), high enough for the jaw to clear the floor (to be confirmed by eye)
DROP_JAW_OPEN_DEG = 60.0     # the widest the jaw was driven (a puck is about as wide as the jaw's opening at less)
DROP_OPEN_S = 0.8            # the jaw stays open this long so the puck falls out
DROP_CLOSE_S = 0.4           # and this long closed before the arm comes down
DROP_BACKUP_TILT_MAX_DEG = 11.0   # with the arm up the body must be within this of level for the caller's back-up (the move gate refuses a move past 12 degrees and lays him down)


def drop_puck(robot, say=print, sleep=time.sleep, *, lift: float = DROP_LIFT_DEG, jaw_open: float = DROP_JAW_OPEN_DEG, open_s: float = DROP_OPEN_S, close_s: float = DROP_CLOSE_S,
              read_arm=None, info: dict | None = None, clock=time.monotonic, attention: bool = False, lower: bool = True) -> str:
    """Raise the arm, open then close the jaw, and (`lower`) lower the arm. `attention` enters the attention pose first (stable with the arm up, but it cannot walk). "ok" or "fell". `robot` is the `SerialRobot` (claw_pose, _tx). Never sends the jaw anything with the arm down.
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
    if attention and hasattr(robot, "sit_down"):             # the attention pose first, as the claw look does: legs straight, no sag. Raising the arm to 120 on a plain stand pitched him nose-up and he fell about 8 seconds in (g2drop, 2026-11-27 16:40; the arm notes say the same of an 8 second jaw sweep)
        say("drop: entering the attention pose")
        if robot.sit_down() == "fell":
            return "fell"
        phase("attention pose")
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
    if not lower:
        info["arm_left_at"] = lift                           # the caller backs up with the arm raised and lowers it itself
        return "ok"
    if robot.claw_pose(0.0, 0.0) == "fell":                  # the arm comes down only after the jaw is closed again
        return "fell"
    phase("lowered")
    tilt()
    note("arm down")
    info["arm_left_at"] = 0.0
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
