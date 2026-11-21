"""The backward catapult (hardware test, docs/hardware/arm-skills.md; plan item 5 in docs/STATUS.md): the object in the claw is thrown over G2's back.

One run = one data skill (`K`, the board plays it itself, nothing is written to the port while it plays) built from the legs the board reports and the settings below, with the body watched, then rest. The move:
  bow      from the stand into a play bow: the rear legs extended, the front legs bent, the rump up (Petoi's own `buttUp` pose), the arm down and the claw holding the object;
  swing    in one frame, at the speed byte given: the front legs extend and the rear legs fold (the body pitches nose-up, Petoi's `launch` pose), the arm's lift joint swings to `--lift-top`, and the jaw opens
           by `--jaw-delta` degrees, which frees the object while the arm is still moving. A frame's joints finish together and ease to a stop at its end (cosine ease), so the jaw is opened INSIDE the swing, not
           after it: the object leaves when the jaw has opened past its width, early in the frame for a large `--jaw-delta` and late for a small one. That is the knob for the release time.
  open     (throw stage) the jaw opens all the way at speed 0 (no interpolation: the claw's fastest, measured on G2 2026-11-21) so nothing is left in it;
  return   the legs back to where they were, the arm down and the jaw closed, slowly (speed 6).
Everything is scaled by `--amount` (0 to 1: how far the legs go from the stand toward the bow and the launch pose), so the first runs are small; `--front-amount` sets the front legs on their own (the full bow, 1.0, lifted the front feet off the floor with the claw and the rear feet taking the weight).

Stages, one after the other (a stage is refused until the one before it has a logged run with the body ok):
  bow    the bow and the return only: does the pose hold him up?
  swing  the bow, the swing with the jaw held shut (no release) and the return: does the arm swing with the legs without tipping him?
  throw  everything, with the release.
G2 on the floor, hands near, a soft surface behind him and clear floor: the arm passes over the pod and the Pi stack, and nose-over (backward onto the pod) is the main risk. `--dry-run` prints the frames and touches nothing.
`--pick` plays Petoi's `pickF` first (the object put in front of him), waits for the board to finish it, and then plays the catapult from where the pick ended: the whole trick.

    python -m pi_pipeline.behavior.catapult --stage bow --amount 0.3 --dry-run
"""
from __future__ import annotations

import json
import os
import time

from . import arm_skill_test as ast
from .arm_speed_test import JAW, LIFT, MAX_NOMINAL_S, SLOW_BYTE, nominal_s, payload_message

STAGES = ("bow", "swing", "throw")
BOW_LEGS = [90, 90, 45, 45, -60, -60, 5, 5]               # Petoi's `buttUp` pose, servo degrees in the order [FLs FRs BRs BLs FLk FRk BRk BLk] (skill_frames.json)
LAUNCH_LEGS = [21, 21, 60, 60, 35, 35, -34, -34]          # frame 1 of Petoi's `launch`: front legs tall, rear legs folded, body pitched up
SIT_LEGS = [45, 45, 105, 105, 45, 45, -45, -45]           # the firmware `sit` pose (also the last frame of `gdb`, good boy): rear legs folded, front legs up, the body pitched up; the old survey look went from `buttUp` (look down) to `ksit` (look up)
LAUNCH_POSES = {"launch": LAUNCH_LEGS, "sit": SIT_LEGS}
LIFT_TOP_MAX = 120.0
JAW_OPEN_DEG = 60.0
JAW_DELTA_MAX = 40.0
AMOUNT_MIN = 0.1
LOG_DIR = "~/g2_runs/catapult"
WATCH_S = 3.0
PICK_MIN_S = 10.0                                           # the earliest the wait may end: the board's end echo is not trusted before this (an older `k` ended it at 0.5 s); lower it only from the times the wait records
PICK_WAIT_S = 12.0                                         # the longest wait for the board to finish `pickF` (it echoes `k` when it does)


FRONT = (0, 1, 4, 5)                                       # positions of the front legs' joints in [FLs FRs BRs BLs FLk FRk BRk BLk]


def mix(a: list, b: list, amount: float, front_amount: float | None = None) -> list:
    """The legs `amount` of the way from `a` to `b`, in whole degrees; the front legs' joints `front_amount` of the way when it is given."""
    return [int(round(x + (amount if front_amount is None or i not in FRONT else front_amount) * (y - x))) for i, (x, y) in enumerate(zip(a, b))]


def build_plan(stage: str, base: list, *, amount: float = 0.3, lift_top: float = 60.0, speed: int = 16, jaw_delta: float = 15.0, jaw_open: float = JAW_OPEN_DEG, front_amount: float | None = None, launch_pose: str = "launch") -> list:
    """The frames of one run, each {"name", "frame", "speed", "delay", "deg", "nominal_s"}, from the 16 angles the board reports (`base`). Raises ValueError for anything out of range."""
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    if not base or len(base) < 16:
        raise ValueError("the 16 joint angles are needed to hold the legs and the arm where they are")
    if not AMOUNT_MIN <= amount <= 1.0:
        raise ValueError(f"amount is {AMOUNT_MIN} to 1.0")
    if launch_pose not in LAUNCH_POSES:
        raise ValueError(f"launch-pose must be one of {tuple(LAUNCH_POSES)}")
    if front_amount is not None and not AMOUNT_MIN <= front_amount <= 1.0:
        raise ValueError(f"front-amount is {AMOUNT_MIN} to 1.0")
    if not isinstance(speed, int) or isinstance(speed, bool) or not 0 <= speed <= 127:
        raise ValueError("the speed byte is a whole number from 0 to 127")
    lift0, jaw0 = float(base[LIFT]), float(base[JAW])
    if not lift0 + 10.0 <= lift_top <= LIFT_TOP_MAX:
        raise ValueError(f"lift-top is the arm's peak: at least 10 degrees above where it is ({lift0:.0f}) and at most {LIFT_TOP_MAX:.0f}")
    if not 0.0 <= jaw_delta <= JAW_DELTA_MAX:
        raise ValueError(f"jaw-delta is 0 to {JAW_DELTA_MAX:.0f} degrees")
    if not 20.0 <= jaw_open <= 120.0:
        raise ValueError("jaw-open is 20 to 120 degrees")
    legs0 = [int(round(a)) for a in base[8:16]]
    bow, launch = mix(legs0, BOW_LEGS, amount, front_amount), mix(legs0, LAUNCH_POSES[launch_pose], amount, front_amount)
    cur = [int(round(a)) for a in base[:16]]
    specs = [("bow", bow, lift0, jaw0, SLOW_BYTE, 8)]                                  # 0.4 s in the bow before anything swings
    if stage != "bow":
        specs.append(("swing", launch, lift_top, jaw0 + (jaw_delta if stage == "throw" else 0.0), speed, 4 if stage == "swing" else 0))
    if stage == "throw":
        specs.append(("open", launch, lift_top, jaw_open, 0, 6))
    specs.append(("return", legs0, lift0, jaw0, SLOW_BYTE, 0))
    plan, total = [], 0.0
    for name, legs, lift, jaw, sp, delay in specs:
        new = list(cur)
        new[8:16] = [int(round(a)) for a in legs]
        new[LIFT], new[JAW] = int(round(lift)), int(round(jaw))
        deg = max(abs(a - b) for a, b in zip(new, cur))
        cur = new
        n = nominal_s(deg, sp, delay)
        total += n
        plan.append({"name": name, "frame": list(new), "speed": sp, "delay": delay, "deg": round(deg, 1), "nominal_s": round(n, 2)})
    if total > MAX_NOMINAL_S:
        raise ValueError(f"the plan takes about {total:.1f} s by the firmware's stepping, more than the {MAX_NOMINAL_S:.0f} s the link stays silent")
    return plan


def previous_stage_ok(stage: str, log_dir: str | None = None) -> str | None:
    """None when `stage` may run, else why not: bow always; swing needs a logged bow run with the body ok, throw a logged swing run with the body ok."""
    if stage == "bow":
        return None
    before = STAGES[STAGES.index(stage) - 1]
    d = os.path.expanduser(log_dir or LOG_DIR)
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(f"_{before}.json"))
    except OSError:
        names = []
    for n in reversed(names):
        try:
            with open(os.path.join(d, n)) as f:
                if json.load(f).get("verdict") == "ok":
                    return None
        except (OSError, ValueError):
            continue
    return f"no logged {before} run with the body ok: run the {before} stage first (--allow-skip skips this check)"


def wait_skill_done(link, max_s: float = PICK_WAIT_S, sleep=time.sleep, clock=time.monotonic, min_s: float = PICK_MIN_S, seen: list | None = None) -> bool:
    """After a behavior skill (`pickF`): wait until the link's silence window ends (the board echoed its `k`), at most `max_s`, and not before `min_s`. True when it ended by itself. The link only notices the `k` when the port is READ, so the
    wait reads it (`drain` writes nothing, so it cannot abort the skill). `min_s` because the first read after the skill found an OLD `k` (the stand-up's) and ended the wait 0.5 s in, with pickF still playing: the next command (a joint read)
    then went out mid-skill (2026-11-21). `seen`, when given, collects (seconds, line) for every line the board sent meanwhile, so the real end echo's time is on record."""
    t0 = clock()
    end = t0 + max_s
    read = getattr(link, "drain", None)
    while clock() < end:
        if clock() - t0 >= min_s and not link._quiet_active():
            return True
        if read is not None:
            lines = read(0.1)
            if lines and seen is not None:
                seen.extend((round(clock() - t0, 1), ln) for ln in lines.splitlines())
        else:
            sleep(0.1)
    return False


def write_log(res: dict, extra: dict) -> str | None:
    return ast.write_log(res, extra, log_dir=LOG_DIR)


def ask_note(ask=input) -> dict:
    """What the person saw, typed in after the run: where the object went and a note (Enter skips)."""
    try:
        return {"landed": ask("where did the object land (inches behind G2, or: stayed / dropped / flew wrong; Enter = not seen): ").strip() or None, "note": ask("note (Enter = none): ").strip() or None}
    except EOFError:
        return {"landed": None, "note": None}


def _parse():
    import argparse
    ap = argparse.ArgumentParser(description="One run of the backward catapult on G2: the person's go first; the voice service stopped.")
    ap.add_argument("--stage", choices=STAGES, required=True)
    ap.add_argument("--amount", type=float, default=0.3, help="how far the legs go toward the bow and launch pose, 0.1 to 1 (default 0.3)")
    ap.add_argument("--front-amount", type=float, default=None, help="the front legs' own amount when it differs (a full bow lifted the front feet off the floor: rear 1.0 with front 0.5 keeps them down)")
    ap.add_argument("--launch-pose", choices=tuple(LAUNCH_POSES), default="launch", help="the legs' pose for the swing: Petoi's launch (default) or the sit pose (rear legs folded deeper, the old look-up pose)")
    ap.add_argument("--lift-top", type=float, default=60.0, help="the arm's peak, degrees (120 at most; default 60 for the first runs)")
    ap.add_argument("--speed", type=int, default=16, help="the swing's speed byte, 0 to 127 (default 16)")
    ap.add_argument("--jaw-delta", type=float, default=15.0, help="throw stage: degrees the jaw opens during the swing, the release knob (large = earlier)")
    ap.add_argument("--jaw-open", type=float, default=JAW_OPEN_DEG)
    ap.add_argument("--pick", action="store_true", help="play pickF first and the catapult from where it ended (the object put in front of him)")
    ap.add_argument("--watch", type=float, default=WATCH_S)
    ap.add_argument("--object", default=None)
    ap.add_argument("--object-oz", type=float, default=None)
    ap.add_argument("--floor", default=None)
    ap.add_argument("--no-prompt", action="store_true")
    ap.add_argument("--allow-skip", action="store_true", help="skip the stage-by-stage check")
    ap.add_argument("--dry-run", action="store_true", help="print the frames, touch nothing")
    return ap.parse_args()


def main() -> None:
    args = _parse()
    params = {"amount": args.amount, "lift_top": args.lift_top, "speed": args.speed, "jaw_delta": args.jaw_delta, "jaw_open": args.jaw_open, "front_amount": args.front_amount, "launch_pose": args.launch_pose}
    why = None if args.allow_skip else previous_stage_ok(args.stage)
    if args.dry_run:
        stand = [0, 0, 0, 0, 0, 0, 0, 0, 20, 20, 30, 30, 30, 30, 30, 30]                 # pickF's last pose: the legs after a pick
        try:
            plan = build_plan(args.stage, stand, **params)
        except ValueError as e:
            print("refused:", e)
            return
        for p in plan:
            print(f"  {p['name']:8s} lift {p['frame'][LIFT]:4d} jaw {p['frame'][JAW]:4d} legs {p['frame'][8:16]} speed {p['speed']:3d} delay {p['delay'] * 0.05:.2f} s  about {p['nominal_s']:.2f} s")
        print(f"stage {args.stage}: " + (f"would be refused ({why})" if why else "may run"))
        return
    if why:
        print("refused:", why)
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
        if args.pick:
            print("playing pickF first: the object in front of him")
            link.send("kpickF", read_reply=False, settle=0.0)
            if not wait_skill_done(link):
                print("pickF did not report its end in time: stopping before the catapult")
                return
        base = chase.read_joints(link)
        if not base or len(base) < 16:
            print("refused: the joint angles could not be read: nothing was sent.")
            return
        try:
            plan = build_plan(args.stage, base, **params)
        except ValueError as e:
            print("refused:", e)
            return
        message = payload_message([{"frame": p["frame"], "speed": p["speed"], "delay": p["delay"]} for p in plan])
        print(f"stage {args.stage}: {len(plan)} frames, about {sum(p['nominal_s'] for p in plan):.1f} s; hands near, soft surface behind him")
        res = ast.run_skill(robot, "catapult_" + args.stage, watch_s=args.watch, send=lambda: link.play_data_skill(message), expect_motion=False)
        path = write_log(res, {"stage": args.stage, "params": params, "plan": plan, "base_joints": base, "picked_first": args.pick, "pack_pct": pct, "pack_v": volts,
                               "object": args.object, "object_oz": args.object_oz, "floor": args.floor})
        print(f"RESULT catapult {args.stage}: body {res['verdict']} (roll {res['max_roll_dev']} pitch {res['max_pitch_dev']} deg){'; logged ' + path if path else ''}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        chase.ensure_rest(link)
    if path and not args.no_prompt:
        ast.update_log(path, {"observed": ask_note()})


if __name__ == "__main__":
    main()
