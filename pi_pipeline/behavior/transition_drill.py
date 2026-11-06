"""The hardware A/B for falls at transitions (user, 2026-11-06). Runs ONLY on the user's go, on hardwood, hands near, the voice service stopped (like claw_look).

A cycle is the transitions that logged falls were made of: pose -> pose -> turn -> stop. Attention pose (`relax`), the back-legs-first stand-up, a firmware turn (alternating left and right), the stop. One variant per run:

    baseline   no gate, no calm stop (what the code did)       calm   the stop waits for a calm moment        gate   the pose gate before the turn        both
    python -m pi_pipeline.behavior.transition_drill --variant calm --cycles 10

The run ends at the first fall (he is then picked up by hand and the round is reported). Result: cycles completed, falls, the worst tilt swing, how often the gate re-seated. Compare variants
by cycles-to-fall and swing; the approach is written into the project guidelines only after one variant shows it clearly beats the baseline (docs/guides/falls-at-transitions.md, not yet written).
"""
from __future__ import annotations

import time

VARIANTS = {"baseline": (False, False), "calm": (True, False), "gate": (False, True), "both": (True, True)}      # name -> (calm stop, pose gate)


def run_variant(robot, cycles: int, *, turn_deg: float = 25.0, turn_s: float = 1.0, say=print, sleep=time.sleep) -> dict:
    """`cycles` of pose -> turn -> stop on a SerialRobot. Stops at the first fall. Returns {"cycles", "fell", "worst_swing_deg", "reseats"}."""
    worst, done, fell = 0.0, 0, False
    for i in range(cycles):
        side = 1 if i % 2 == 0 else -1
        if robot.relax() != "ok":
            fell = True
            break
        sleep(1.0)
        if robot.stand_up_from_attention() == "fell":                  # the pose -> pose move the logged falls follow: attention pose to the back-legs-first stand-up
            fell = True
            break
        state = robot.turn(side * turn_deg, turn_s)                    # the gate if on, the turn, the calm stop (turn() does not stand him up itself: the standing flow sends nothing before a move)
        worst = max(worst, robot.swing_deg())
        say(f"cycle {i + 1}/{cycles}: turn {'right' if side > 0 else 'left'} -> {state}, swing {robot.swing_deg():.0f} deg, re-seats so far {robot.gate_reseats}")
        if state == "fell":
            fell = True
            break
        done += 1
        sleep(1.0)
    return {"cycles": done, "fell": fell, "worst_swing_deg": round(worst, 1), "reseats": robot.gate_reseats}


def main() -> None:
    import argparse

    from . import ball_chase as chase
    ap = argparse.ArgumentParser(description="Falls at transitions: one A/B variant.")
    ap.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    ap.add_argument("--cycles", type=int, default=10)
    args = ap.parse_args()
    chase.STOP_CALM, chase.POSE_GATE = VARIANTS[args.variant]
    from ..link.serial_link import SerialLink
    from ..power import battery
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    robot = chase.SerialRobot(link)
    try:
        chase._stand_if_lying(link, "kbalance")
        res = run_variant(robot, args.cycles)
        print("RESULT", args.variant, res)
    except KeyboardInterrupt:
        print("ended")
    finally:
        try:
            link.send("krest", read_reply=False, settle=0.0)
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
