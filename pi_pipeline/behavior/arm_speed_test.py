"""The arm speed series: one speed step per run, G2 standing, the owner's go before each (hardware test, docs/hardware/arm-skills.md).

Why: the throw trick needs the arm's lift to swing fast and the claw to open just before the top of the arc, and nothing known gives the real speeds. The firmware moves every joint of a skill frame together and
finishes them together: a frame takes `largest joint change in degrees / (speed byte / 8)` steps of about 8 ms plus the servo write time (`transform()` in OpenCat's `motion.h`, read 2026-11-20, NOT yet measured on
this board), and the speed byte is an int8, so 127 is the most it can ask. The claw look moves the arm at about 60 degrees a second (the Pi sends one position command at a time); the baseline of this series is the same
pace as a data skill, a speed byte of about 4. The servo's own limit, not the firmware's, is what the series looks for.

One run = one `K` data skill played by the board itself (nothing is written to the board while it plays: any byte waiting on the port aborts a behavior skill), built from the joint angles the board reports so the legs
stay where they are. Two series:
  lift: the lift joint goes to `--lift-lo`, up to `--lift-hi` (120 at most, the claw look's height) at the step's speed, holds half a second, and comes back down slowly.
  jaw : the arm is raised slowly to `--lift-hold` first (the claw drags on the floor from the carry position), the jaw goes to `--jaw-open` slowly, closes to `--jaw-closed` at the step's speed, opens again at the
        same speed, goes back to where it was and the arm comes down slowly. `--jaw-open` and `--jaw-closed` have no defaults: the sign and range of the jaw joint differ between the arm skills, so they are
        read off a measurement, never guessed.
The IMU trace of the body (time since the skill was sent, pitch, roll) and the send time are logged; the real arm position is not available (the board reports commanded angles), so the owner's read after each
run is the main data. The next step is refused unless the last run of the series has an observation and is at most one step above it (`SPEED_STEPS`), and a step above a `stalled`, `hit` or `unsafe` run is refused.

    python -m pi_pipeline.behavior.arm_speed_test --series lift --speed 4
    python -m pi_pipeline.behavior.arm_speed_test --series lift --speed 6 --dry-run     (prints the plan, touches nothing)
"""
from __future__ import annotations

import glob
import json
import os
import time

from . import arm_skill_test as ast

SERIES = ("lift", "jaw")
SPEED_STEPS = (4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 127)   # raw speed bytes, one step per run: 4 is about the claw look's 60 deg/s, 127 the int8 limit
SLOW_BYTE = 6                                              # the positioning and return legs of a run (about 90 deg/s commanded), never the speed under test
STEP_S = 0.008                                             # the firmware waits (16 - 0) / 2 = 8 ms after each interpolation step (motion.h); the servo write time comes on top and is not known
HOLD_RAW = 10                                              # the pause after the fast leg, x 50 ms (0.5 s): the arm stops and the body settles before the way back
LIFT_MAX_DEG = 120.0                                       # the most the Pi asks of the lift servo (ball_chase.CLAW_LIFT_MAX_DEG): near the top of the servo, and the height the claw look uses
JAW_MAX_DEG = 120.0
MAX_NOMINAL_S = 8.0                                        # the link keeps the port silent for 10 s after a behavior skill (G2_SKILL_QUIET_S); a plan longer than this is refused
PAN, LIFT, JAW = 0, 1, 2
STOP_RESULTS = ("stalled", "hit", "unsafe")
RESULTS = {"f": "followed", "l": "lagged", "s": "stalled", "h": "hit", "u": "unsafe", "n": "nothing"}
LOG_DIR = "~/g2_runs/arm_speed"
WATCH_S = 9.0


def ratio(speed_byte: float) -> float:
    return speed_byte / 8.0


def nominal_s(deg: float, speed_byte: float, delay_raw: int = 0) -> float:
    """How long the firmware's own stepping takes for a move of `deg` degrees at `speed_byte`, plus the pause after the frame. Excludes the servo write time per step, so the real time is longer."""
    steps = int(round(deg / ratio(speed_byte))) if speed_byte > 0 else 0
    return steps * STEP_S + delay_raw * 0.05


def upper_deg_s(speed_byte: float) -> float:
    """The most degrees a second the firmware's stepping can command at this byte (one degree-ratio per 8 ms step); the cosine ease peaks about 1.6 times higher, the servo write time lowers it."""
    return ratio(speed_byte) / STEP_S


def _i(v: float) -> int:
    return int(round(v))


def build_plan(series: str, speed: int, base: list, *, lift_lo: float = 0.0, lift_hi: float = LIFT_MAX_DEG, lift_hold: float = LIFT_MAX_DEG, jaw_open: float | None = None, jaw_closed: float | None = None) -> list:
    """The steps of one run, each {"name", "joints": {index: angle}, "speed", "delay", "deg", "nominal_s"}, from the 16 angles the board reports (`base`). Raises ValueError for anything out of range."""
    if series not in SERIES:
        raise ValueError(f"series must be one of {SERIES}")
    if not isinstance(speed, int) or isinstance(speed, bool) or not 1 <= speed <= 127:
        raise ValueError("the speed byte is a whole number from 1 to 127")
    if not base or len(base) < 16:
        raise ValueError("the 16 joint angles are needed to hold the legs where they are")
    if not 0.0 <= lift_lo < lift_hi <= LIFT_MAX_DEG:
        raise ValueError(f"lift needs 0 <= lo < hi <= {LIFT_MAX_DEG:.0f}")
    if not 0.0 <= lift_hold <= LIFT_MAX_DEG:
        raise ValueError(f"the raised height is 0 to {LIFT_MAX_DEG:.0f}")
    specs = []
    if series == "lift":
        specs = [("to_start", {LIFT: lift_lo}, SLOW_BYTE, 4), ("lift_up", {LIFT: lift_hi}, speed, HOLD_RAW), ("lower", {LIFT: lift_lo}, SLOW_BYTE, 0)]
    else:
        if jaw_open is None or jaw_closed is None:
            raise ValueError("the jaw series needs --jaw-open and --jaw-closed (no defaults: read them off the jaw joint first)")
        if abs(jaw_open) > JAW_MAX_DEG or abs(jaw_closed) > JAW_MAX_DEG or jaw_open == jaw_closed:
            raise ValueError(f"the jaw angles must differ and stay within +-{JAW_MAX_DEG:.0f}")
        jaw0 = float(base[JAW])
        specs = [("raise", {LIFT: lift_hold}, SLOW_BYTE, 6), ("jaw_open_slow", {JAW: jaw_open}, SLOW_BYTE, 6), ("jaw_close", {JAW: jaw_closed}, speed, HOLD_RAW),
                 ("jaw_open", {JAW: jaw_open}, speed, HOLD_RAW), ("jaw_back", {JAW: jaw0}, SLOW_BYTE, 4), ("lower", {LIFT: lift_lo}, SLOW_BYTE, 0)]
    cur = [float(a) for a in base[:16]]
    plan, total = [], 0.0
    for name, joints, sp, delay in specs:
        deg = max(abs(a - cur[j]) for j, a in joints.items())
        for j, a in joints.items():
            cur[j] = a
        n = nominal_s(deg, sp, delay)
        total += n
        plan.append({"name": name, "joints": {int(j): a for j, a in joints.items()}, "speed": sp, "delay": delay, "deg": round(deg, 1), "nominal_s": round(n, 2), "frame": [_i(x) for x in cur]})
    if total > MAX_NOMINAL_S:
        raise ValueError(f"the plan takes about {total:.1f} s by the firmware's own stepping, more than the {MAX_NOMINAL_S:.0f} s the link stays silent; use a smaller range")
    return plan


def payload_message(plan: list) -> bytes:
    """The wire bytes (`K` ... `~`) of a plan: the legs stay at the angles in `base`, the pan at 0 unless the base had it elsewhere."""
    from ..link import kskill
    return kskill.message(kskill.behavior_payload([p["frame"] for p in plan], [p["speed"] for p in plan], [p["delay"] for p in plan]))


# ---------------------------------------------------------------------------------------------------- one step at a time
def last_run(series: str, log_dir: str | None = None) -> dict | None:
    """The newest logged run of `series` (its `speed_byte` and `observation`), or None."""
    d = os.path.expanduser(log_dir or LOG_DIR)
    for path in sorted(glob.glob(os.path.join(d, f"*_{series}_s*.json")), reverse=True):
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data.get("speed_byte"), int):
                return data
        except (OSError, ValueError):
            continue
    return None


def check_step(speed: int, last: dict | None, allow_jump: bool = False) -> str | None:
    """None when this speed may be run, else why not: the first run of a series is the baseline step, each next one is at most one step above the last, and none goes above a run that stalled, hit something or
    was unsafe, or one whose observation was never recorded. Repeating or lowering a speed is always allowed."""
    if allow_jump:
        return None
    if last is None:
        return None if speed <= SPEED_STEPS[0] else f"no earlier run of this series: start at the baseline step, speed {SPEED_STEPS[0]}"
    prev = int(last["speed_byte"])
    if speed <= prev:
        return None
    result = (last.get("observation") or {}).get("result")
    if result is None:
        return f"the last run (speed {prev}) has no recorded observation: record it before going higher"
    if result in STOP_RESULTS:
        return f"the last run (speed {prev}) was {result}: not going higher"
    above = [s for s in SPEED_STEPS if s > prev]
    nxt = above[0] if above else prev
    if speed > nxt:
        return f"one step at a time: after speed {prev} the next step is {nxt}"
    return None


def ask_observation(ask=input) -> dict:
    """What the owner saw and heard, typed in after the run: one letter for the result, then free text."""
    try:
        r = ask("what did it do? f followed the command, l lagged behind it, s stalled, h hit something, u unsafe (stop here), n nothing moved: ").strip().lower()[:1]
        out = {"result": RESULTS.get(r)}
        out["sound"] = ask("sound (Enter = nothing unusual): ").strip() or None
        out["note"] = ask("note (Enter = none): ").strip() or None
        return out
    except EOFError:
        return {"result": None, "sound": None, "note": None}


def run_step(robot, link, series: str, speed: int, base: list, *, watch_s: float = WATCH_S, say=print, sleep=time.sleep, clock=time.monotonic, wall=time.time, **params) -> tuple:
    """Build the plan and play it as one data skill while the body is watched. Returns (result, plan). Never raises past the tilt watch; a refused plan raises ValueError before anything is sent."""
    plan = build_plan(series, speed, base, **params)
    message = payload_message(plan)
    label = f"{series}_s{speed:03d}"
    res = ast.run_skill(robot, label, watch_s=watch_s, say=say, sleep=sleep, clock=clock, wall=wall, send=lambda: link.play_data_skill(message), expect_motion=False)
    return res, plan


def _parse() -> "argparse.Namespace":  # noqa: F821
    import argparse
    ap = argparse.ArgumentParser(description="One step of the arm speed series on G2: the owner's go before each run; the voice service stopped.")
    ap.add_argument("--series", required=True, choices=SERIES)
    ap.add_argument("--speed", type=int, required=True, help="the speed byte under test, steps: " + ", ".join(str(s) for s in SPEED_STEPS))
    ap.add_argument("--lift-lo", type=float, default=0.0)
    ap.add_argument("--lift-hi", type=float, default=LIFT_MAX_DEG, help="lift series: the top of the swing (120 at most)")
    ap.add_argument("--lift-hold", type=float, default=LIFT_MAX_DEG, help="jaw series: the height the arm is raised to first")
    ap.add_argument("--jaw-open", type=float, default=None)
    ap.add_argument("--jaw-closed", type=float, default=None)
    ap.add_argument("--watch", type=float, default=WATCH_S)
    ap.add_argument("--object", default=None)
    ap.add_argument("--object-oz", type=float, default=None)
    ap.add_argument("--floor", default=None)
    ap.add_argument("--no-prompt", action="store_true")
    ap.add_argument("--allow-jump", action="store_true", help="the owner's call: skip the one-step-at-a-time check")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the check, touch nothing")
    return ap.parse_args()


def main() -> None:
    args = _parse()
    params = {"lift_lo": args.lift_lo, "lift_hi": args.lift_hi, "lift_hold": args.lift_hold, "jaw_open": args.jaw_open, "jaw_closed": args.jaw_closed}
    why = check_step(args.speed, last_run(args.series), args.allow_jump)
    if why:
        print("refused:", why)
        return
    if args.dry_run:
        try:
            plan = build_plan(args.series, args.speed, [0] * 16, **params)
        except ValueError as e:
            print("refused:", e)
            return
        for p in plan:
            print(f"  {p['name']:14s} joints {p['joints']} speed {p['speed']:3d} delay {p['delay'] * 0.05:.2f} s  {p['deg']:5.1f} deg  about {p['nominal_s']:.2f} s")
        print(f"speed {args.speed}: at most {upper_deg_s(args.speed):.0f} deg/s commanded by the firmware's stepping (the servo write time lowers it)")
        return
    from . import ball_chase as chase
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
    path = None
    try:
        chase._stand_if_lying(link, "kbalance")
        base = chase.read_joints(link)
        if not base or len(base) < 16:
            print("refused: the joint angles could not be read, so the legs cannot be held: nothing was sent.")
            return
        print(f"joints before: lift {base[LIFT]} jaw {base[JAW]}")
        try:
            plan = build_plan(args.series, args.speed, base, **params)
        except ValueError as e:
            print("refused:", e)
            return
        print(f"speed {args.speed}: the lift leg takes about {max(p['nominal_s'] for p in plan):.2f} s by the firmware's stepping; hands near")
        res, plan = run_step(robot, link, args.series, args.speed, base, watch_s=args.watch, **params)
        volts_after = battery.read_voltage(link)
        meta = {"series": args.series, "speed_byte": args.speed, "speed_ratio": ratio(args.speed), "upper_deg_s": round(upper_deg_s(args.speed), 1), "plan": plan,
                "nominal_total_s": round(sum(p["nominal_s"] for p in plan), 2), "params": params, "base_joints": base, "pack_pct": pct, "pack_v": volts, "pack_pct_after": battery.pack_percent(volts_after) if volts_after else None,
                "object": args.object, "object_oz": args.object_oz, "floor": args.floor}
        path = ast.write_log(res, meta, log_dir=LOG_DIR)
        print(f"RESULT {args.series} speed {args.speed}: body {res['verdict']} (roll {res['max_roll_dev']} pitch {res['max_pitch_dev']} deg){'; logged ' + path if path else ''}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        from .ball_chase import ensure_rest
        ensure_rest(link)
    if path and not args.no_prompt:
        ast.update_log(path, {"observation": ask_observation()})


if __name__ == "__main__":
    main()
