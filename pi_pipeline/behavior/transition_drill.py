"""The hardware A/B for falls at transitions (user, 2026-11-06). Runs ONLY on the user's go, on hardwood, hands near, the voice service stopped (like claw_look).

A cycle is the transitions that logged falls were made of, back to back: attention pose, a full claw look, the back-legs-first stand-up, a firmware turn and at once a turn the other way, with a stop after each. One variant per run:

    baseline   no gate, no calm stop (what the code did)       calm   the stop waits for a calm moment        gate   the pose gate before the turn        both
    python -m pi_pipeline.behavior.transition_drill --variant calm --cycles 10

The run ends at the first fall (he is then picked up by hand and the round is reported). Result: cycles completed, falls, the worst tilt swing, how often the gate re-seated. Compare variants
by cycles-to-fall and swing; the approach is written into the project guidelines only after one variant shows it clearly beats the baseline (docs/guides/falls-at-transitions.md, not yet written).
"""
from __future__ import annotations

import time

VARIANTS = {"baseline": (False, False), "calm": (True, False), "gate": (False, True), "both": (True, True)}      # name -> (calm stop, pose gate)


NEAR_FALL_DEG = 20.0      # a tilt swing this big in one phase counts as a near fall (most falls are never recorded, so variants are compared on swings too)


def run_variant(robot, cycles: int, *, turn_deg: float = 25.0, turn_s: float = 1.0, look=None, say=print, sleep=time.sleep) -> dict:
    """`cycles` of the pattern the logged falls follow, with no rest between cycles: attention pose, a full claw look (arm up, left, right, centre, down), the back-legs-first stand-up, a turn, and at
    once a turn back the other way. Stops at the first fall. `look(robot)` makes the claw look (default: claw_survey.run_claw_look without pictures). Returns
    {"cycles", "fell", "worst_swing_deg", "near_falls", "reseats"}."""
    if look is None:
        from . import claw_survey
        look = lambda r: claw_survey.run_claw_look(r._lk, None, "drill", stopped=r.fallen)      # noqa: E731
    worst, near, done, fell = 0.0, 0, 0, False

    legs_off: list = []

    def trace(phase: str) -> None:
        """The IMU tilt through a phase (pitch / roll min and max, and the last readings), so a fall leaves something to read."""
        p, r = list(getattr(robot, "_pitch", []) or []), list(getattr(robot, "_roll", []) or [])
        if p and r:
            say(f"   {phase} tilt: pitch {min(p):+.0f}..{max(p):+.0f}, roll {min(r):+.0f}..{max(r):+.0f}; last pitch {[round(x) for x in p[-6:]]} roll {[round(x) for x in r[-6:]]}")

    def note(phase: str) -> None:
        nonlocal worst, near
        sw = robot.swing_deg()
        worst = max(worst, sw)
        if sw >= NEAR_FALL_DEG:
            near += 1
        say(f"   {phase}: swing {sw:.0f} deg")
        trace(phase)
        bad = getattr(robot, "last_leg_check", None)
        if phase.startswith("stand-up") and bad:
            legs_off.append(bad)
            say(f"   LEGS OFF their stand angle after the stand-up: {bad}")

    for i in range(cycles):
        side = 1 if i % 2 == 0 else -1
        r_state = robot.relax()
        trace("attention pose")
        if r_state != "ok" or robot.fallen():                         # a fall anywhere ends the round at once: nothing more is sent to a fallen G2
            trace("fall in the attention pose")
            fell = True
            break
        look(robot)
        trace("claw look")
        if robot.fallen():
            trace("fall")
            fell = True
            break
        if robot.stand_up_from_attention() == "fell":
            fell = True
            break
        note("stand-up from attention")
        for k, deg in enumerate((side * turn_deg, -side * turn_deg)):
            state = robot.turn(deg, turn_s)
            note(f"turn {'right' if deg > 0 else 'left'}")
            if state == "fell":
                fell = True
                break
        say(f"cycle {i + 1}/{cycles}: {'FELL' if fell else 'ok'}, re-seats so far {robot.gate_reseats}")
        if fell:
            break
        done += 1
    return {"cycles": done, "fell": fell, "worst_swing_deg": round(worst, 1), "near_falls": near, "reseats": robot.gate_reseats, "stand_ups_with_legs_off": len(legs_off)}


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
    import logging
    board_moves: list = []

    class _Watch(logging.Handler):                      # the BiBoard's own voice module starting a move (a spoken word, a TV): that round is void, not a fall caused by the transitions
        def emit(self, record):
            if "started a move the Pi did not send" in record.getMessage():
                board_moves.append(record.getMessage()[-60:])
    logging.getLogger("g2.command_log").addHandler(_Watch())
    logging.getLogger().addHandler(_Watch())
    robot = chase.SerialRobot(link)
    try:
        chase._stand_if_lying(link, "kbalance")
        res = run_variant(robot, args.cycles)
        if board_moves:
            res["void"] = f"the board started a move on its own during the round: {board_moves[-1]}"
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
