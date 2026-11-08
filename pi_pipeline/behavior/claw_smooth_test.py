"""Try the claw raise at several speeds and step rates so the smoothest can be picked by eye (owner, 2026-11-08: "I see that same jerkiness when we raise the claw in the claw look").

Runs ONLY on the owner's go, G2 on the floor, hands near, the voice service stopped. G2 goes to the attention pose (`kcalib`, where the claw look raises it), then for each setting raises the claw to the look height,
holds a moment, lowers it, and says which setting it was; then he stands up and rests. Stops at the first fall (nothing more is sent).

    python -m pi_pipeline.behavior.claw_smooth_test            # the default set of settings
    python -m pi_pipeline.behavior.claw_smooth_test --set 40:40 --set 60:20     # speed deg/s : steps a second
"""
from __future__ import annotations

import math
import time

DEFAULT_SETS = ["60:40", "40:40", "60:100", "30:60"]          # the current look, slower, finer steps, slow and fine


def raise_and_lower(link, lift: float, speed: float, rate: int, curve, sleep=time.sleep, say=print, hold_s: float = 1.2) -> None:
    """Raise the lift servo (joint 1) from 0 to `lift` at about `speed` deg/s with `rate` commands a second along `curve(u)`, hold, and lower it the same way."""
    steps = max(2, int(math.ceil(lift / speed * rate)))
    for rev in (False, True):
        for i in range(1, steps + 1):
            u = curve(i / steps)
            a = lift * (1 - u) if rev else lift * u
            link.send(f"i1 {int(round(a))}", read_reply=False, settle=0.0)
            sleep(1.0 / rate)
        if not rev:
            sleep(hold_s)


def smoothstep(u: float) -> float:
    return u * u * (3 - 2 * u)


def main() -> None:
    import argparse

    from . import ball_chase as chase
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", help="speed:rate, for example 60:40 (deg/s, commands a second); repeatable")
    args = ap.parse_args()
    sets = args.set or DEFAULT_SETS
    import subprocess
    if subprocess.run(["systemctl", "is-active", "g2-voice"], capture_output=True, text=True).stdout.strip() == "active":
        print("the g2-voice service is RUNNING: stop it first (pi_pipeline/behavior/service_off.sh). Nothing was moved.")
        return
    from ..link.serial_link import SerialLink
    link = SerialLink("/dev/serial0")
    link.connect()
    robot = chase.SerialRobot(link, fall_deg=30.0)
    fell = False
    try:
        chase._stand_if_lying(link, "kbalance")
        if robot.relax() != "ok" or robot.fallen():
            fell = True
            print("fell in the attention pose: stopping")
            return
        for item in sets:
            speed, rate = (float(x) for x in item.split(":"))
            print(f"--- raise/lower at {speed:.0f} deg/s, {rate:.0f} commands a second ({item}) ---", flush=True)
            time.sleep(1.0)
            raise_and_lower(link, chase.CLAW_LIFT_DEG, speed, int(rate), smoothstep)
            if robot.fallen():
                fell = True
                print("fell: stopping")
                return
            time.sleep(2.0)
        robot.stand_up_from_attention()
    except KeyboardInterrupt:
        print("ended")
    finally:
        if not fell:
            link.send("krest", read_reply=False, settle=0.0)


if __name__ == "__main__":
    main()
