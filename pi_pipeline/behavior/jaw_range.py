"""The jaw range helper: find the two jaw angles the speed series needs (hardware test, docs/hardware/arm-skills.md).

`g2armspeed --series jaw` takes `--jaw-open` and `--jaw-closed` with no defaults, because the jaw joint's sign and range differ between the arm skills and nothing recorded says which is which on G2's claw. This tool
measures them by eye: G2 stands (the eased stand-up), the arm is raised the way the claw look raises it (`claw_pose`, so the claw is clear of the floor), then the jaw is stepped from where it is toward `--to` in small steps
(`--step` degrees, at most `STEP_MAX_DEG`, never more than `SPAN_MAX_DEG` from the start in one run) with a pause after each, printing the commanded angle of every step with a step number. The person watching says afterwards
which angle looked fully open, which fully closed, and where it stopped moving (a jaw that meets its stop or an object). Then the jaw goes back to where it started in steps, the arm comes down and G2 is laid in rest.

The board reports COMMANDED angles, so the numbers printed are what was sent, not where the jaw is; the person's eye is the measurement. The run keeps him standing for about a quarter of a minute at most (legs have gone limp after
about ten seconds of standing still before): `--to` small first, then larger.

    python -m pi_pipeline.behavior.jaw_range --to 40
"""
from __future__ import annotations

import json
import os
import time

STEP_DEG = 10.0
STEP_MAX_DEG = 15.0
SPAN_MAX_DEG = 60.0
JAW_MAX_DEG = 120.0
MAX_STEPS = 12
HOLD_OUT_S = 0.8                    # the pause after each step going out, long enough to see where the jaw is
HOLD_BACK_S = 0.3                   # and coming back
LIFT_HOLD_DEG = 120.0               # the arm is raised to the claw look's height first
LOG_DIR = "~/g2_runs/jaw_range"
JAW = 2


def sweep_angles(start: float, target: float, step: float = STEP_DEG) -> list:
    """The whole-degree angles from just past `start` to `target` in steps of at most `step` (the last one is exactly `target`). Raises ValueError for a target out of range, a span over SPAN_MAX_DEG, a step out of
    range, no span at all or more than MAX_STEPS steps."""
    if abs(target) > JAW_MAX_DEG:
        raise ValueError(f"the jaw target must stay within +-{JAW_MAX_DEG:.0f}")
    if not 0 < step <= STEP_MAX_DEG:
        raise ValueError(f"the step is 1 to {STEP_MAX_DEG:.0f} degrees")
    span = target - start
    if abs(span) < 1:
        raise ValueError("the target is where the jaw already is")
    if abs(span) > SPAN_MAX_DEG:
        raise ValueError(f"at most {SPAN_MAX_DEG:.0f} degrees from the start in one run: use a nearer --to first")
    n = int(-(-abs(span) // step))
    if n > MAX_STEPS:
        raise ValueError(f"{n} steps is more than {MAX_STEPS}: use a larger --step or a nearer --to")
    return [int(round(start + span * k / n)) for k in range(1, n + 1)]


def run_sweep(robot, start: int, target: float, step: float = STEP_DEG, *, say=print, sleep=time.sleep) -> dict:
    """With G2 standing: raise the arm, step the jaw out to `target` and back to `start`, lower the arm. Returns {"steps": [[n, angle], ...], "state"}: "ok" or "fell". Never sends the jaw anything with the arm down."""
    out = sweep_angles(start, target, step)
    back = sweep_angles(target, start, step)
    rec = {"start": start, "target": target, "step": step, "steps": [], "state": "ok", "lift_hold": LIFT_HOLD_DEG}
    say(f"standing for about {len(out) * HOLD_OUT_S + len(back) * HOLD_BACK_S + 4:.0f} s: raising the arm first")
    if robot.claw_pose(0.0, LIFT_HOLD_DEG) == "fell":
        rec["state"] = "fell"
        return rec
    robot._tx("gP")
    n = 0
    for phase, angles, hold in (("out", out, HOLD_OUT_S), ("back", back, HOLD_BACK_S)):
        for a in angles:
            n += 1
            robot._tx(f"i2 {a}")
            rec["steps"].append([n, a, phase])
            say(f"  step {n:2d} ({phase}): jaw commanded to {a}")
            sleep(hold)
            if robot._fell():
                rec["state"] = "fell"
                say("G2 fell: stopping")
                return rec
    sleep(0.5)
    if robot.claw_pose(0.0, 0.0) == "fell":                    # the arm comes down only after the jaw is back
        rec["state"] = "fell"
    return rec


def ask_marks(ask=input) -> dict:
    """The angles the person saw, typed in after the run (Enter skips one)."""
    def num(prompt):
        try:
            return float(ask(prompt).strip())
        except (ValueError, EOFError):
            return None
    out = {"open": num("which commanded angle looked fully OPEN (Enter = not seen): "), "closed": num("which commanded angle looked fully CLOSED (Enter = not seen): "),
           "stopped_at": num("the angle where it stopped moving or met something (Enter = never): ")}
    try:
        out["note"] = ask("note (Enter = none): ").strip() or None
    except EOFError:
        out["note"] = None
    return out


def command_line(marks: dict, speed: int = 4) -> str | None:
    """The `g2armspeed` jaw command for the angles the person marked, or None when either is missing."""
    if marks.get("open") is None or marks.get("closed") is None:
        return None
    return f"g2armspeed --series jaw --speed {speed} --jaw-open {marks['open']:g} --jaw-closed {marks['closed']:g}"


def write_log(rec: dict) -> str | None:
    try:
        d = os.path.expanduser(LOG_DIR)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, time.strftime("%Y%m%d_%H%M%S") + "_jaw_range.json")
        with open(path, "w") as f:
            json.dump({**rec, "time": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=1)
        return path
    except OSError:
        return None


def main() -> None:
    import argparse

    from . import ball_chase as chase
    ap = argparse.ArgumentParser(description="Step the jaw toward --to in small steps with the arm raised, so the jaw angles for the speed series can be read by eye. The person's go first; the voice service stopped.")
    ap.add_argument("--to", type=float, required=True, help="the jaw angle to step toward (within 60 degrees of where it starts)")
    ap.add_argument("--step", type=float, default=STEP_DEG)
    ap.add_argument("--no-prompt", action="store_true")
    args = ap.parse_args()
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
    rec, path = None, None
    try:
        chase._stand_if_lying(link, "kbalance")
        joints = chase.read_joints(link)
        if not joints or len(joints) < 3:
            print("refused: the joint angles could not be read: nothing was moved.")
            return
        start = int(joints[JAW])
        try:
            sweep_angles(start, args.to, args.step)
        except ValueError as e:
            print("refused:", e)
            return
        print(f"the jaw reads {start} now; stepping it toward {args.to:g}")
        rec = run_sweep(robot, start, args.to, args.step)
        rec.update(pack_pct=pct, pack_v=volts)
        path = write_log(rec)
        print(f"sweep {rec['state']}{'; logged ' + path if path else ''}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        chase.ensure_rest(link)
    if rec and rec["state"] == "ok" and not args.no_prompt:
        marks = ask_marks()
        if path:
            from .arm_skill_test import update_log
            update_log(path, {"marks": marks})
        line = command_line(marks)
        print("next:", line if line else "no open and closed angles marked yet")


if __name__ == "__main__":
    main()
