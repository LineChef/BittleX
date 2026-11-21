"""The scripted-skill player (hardware tool; the second half of authoring a scripted movement, skill `author-movement`): a movement written as keyframes, played by the board as one data skill.

A script is a JSON file in `pi_pipeline/behavior/scripts/NAME.json`:
  {"name": "...", "description": "...", "frames": [
      {"name": "bow", "pose": "bow", "speed": 6, "delay_s": 0.4},
      {"name": "swing", "pose": "launch", "joints": ["legs", "lift"], "speed": 127, "delay_s": 0.0},
      {"name": "back", "pose": "start", "speed": 6}]}
`pose` is a pose saved by the pose editor (`g2poseedit save`, kept on the Pi in `~/g2_runs/pose_edit/poses/`, or in `pi_pipeline/behavior/scripts/poses/` once it is committed), the word `start` (the 16 angles read when the run began), or `angles`
(16 numbers) in place of it. `joints` (names or groups of the pose editor) limits which joints the frame takes from the pose; the rest keep their last value. `speed` is the raw speed byte of the frame (the ratio is speed/8: 6 is a
slow ease, 127 the fastest eased move, 0 an instant jump) and `delay_s` the pause after the frame (50 ms steps). A frame's joints move together and ease to a stop at its end.

`--amount` (0.1 to 1) scales every pose from the starting angles toward the pose, so a first run is small. The run plays from the eased stand-up (or the attention pose with `--attention`), watches the body, and lays him in rest.
`--dry-run` prints the frames and touches nothing.

    python -m pi_pipeline.behavior.scripted_skill NAME --amount 0.3 --dry-run
"""
from __future__ import annotations

import json
import os
import time

from . import arm_skill_test as ast
from .arm_speed_test import MAX_NOMINAL_S, nominal_s, payload_message
from .pose_edit import GROUPS, NAMES, load_pose

SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "scripts")
LOG_DIR = "~/g2_runs/scripts"
WATCH_S = 3.0
AMOUNT_MIN = 0.1


def _pose_angles(name: str) -> list:
    """A committed pose (`scripts/poses/`) wins over one saved on the Pi, so a script plays what was reviewed and committed."""
    try:
        with open(os.path.join(SCRIPT_DIR, "poses", name + ".json")) as f:
            return json.load(f)["angles"]
    except OSError:
        return load_pose(name)


def joint_indices(spec: list | None) -> list:
    """The joint indices a frame takes from its pose: every joint when `spec` is None, else the named joints and groups. Raises ValueError for a name it does not know."""
    if spec is None:
        return list(range(16))
    out = []
    for n in spec:
        for m in GROUPS.get(n, [n]):
            if m not in NAMES or (m.startswith("j") and m != "jaw"):
                raise ValueError(f"unknown joint {n!r}")
            out.append(NAMES.index(m))
    return sorted(set(out))


def parse_overrides(items: list | None) -> dict:
    """`["lunge.jaw=30"]` -> {("lunge", "jaw"): 30.0}. Raises ValueError for anything else."""
    out = {}
    for it in items or []:
        try:
            key, val = it.split("=")
            frame, joint = key.split(".")
            if joint not in ("speed", "delay_s") and (joint not in NAMES or (joint.startswith("j") and joint != "jaw")):
                raise ValueError
            out[(frame.strip(), joint.strip())] = float(val)
        except ValueError:
            raise ValueError(f"not an override: {it!r} (FRAME.JOINT=ANGLE, for example lunge.jaw=30)") from None
    return out


def build_plan(script: dict, base: list, *, amount: float = 1.0, pose_lookup=_pose_angles, overrides: dict | None = None) -> list:
    """The frames of one run, each {"name", "frame", "speed", "delay", "deg", "nominal_s"}. Raises ValueError for a script or value out of range."""
    if not base or len(base) < 16:
        raise ValueError("the 16 joint angles are needed")
    if not AMOUNT_MIN <= amount <= 1.0:
        raise ValueError(f"amount is {AMOUNT_MIN} to 1.0")
    frames = script.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("a script needs a list of frames")
    start = [float(a) for a in base[:16]]
    cur = list(start)
    plan, total = [], 0.0
    for k, fr in enumerate(frames):
        name = str(fr.get("name") or f"frame{k + 1}")
        ov = {k[1]: v for k, v in (overrides or {}).items() if k[0] == str(fr.get("name"))}
        speed = int(ov["speed"]) if "speed" in ov else fr.get("speed", 12)
        if not isinstance(speed, int) or isinstance(speed, bool) or not 0 <= speed <= 127:
            raise ValueError(f"{name}: speed is a whole number from 0 to 127")
        delay_s = float(ov["delay_s"]) if "delay_s" in ov else float(fr.get("delay_s", 0.0))
        if not 0.0 <= delay_s <= 5.0:
            raise ValueError(f"{name}: delay_s is 0 to 5")
        if "angles" in fr:
            target = [float(a) for a in fr["angles"]]
            if len(target) != 16:
                raise ValueError(f"{name}: angles needs 16 numbers")
        elif fr.get("pose") == "start":
            target = list(start)
        elif fr.get("pose"):
            target = [float(a) for a in pose_lookup(fr["pose"])]
        else:
            raise ValueError(f"{name}: a frame needs a pose or angles")
        new = list(cur)
        for i in joint_indices(fr.get("joints")):
            new[i] = start[i] + amount * (target[i] - start[i]) if fr.get("pose") != "start" else target[i]
            new[i] = max(-125.0, min(125.0, new[i]))
        for jn, val in {**(fr.get("set") or {}), **{k: v for k, v in ov.items() if k not in ("speed", "delay_s")}}.items():
            if jn not in NAMES:
                raise ValueError(f"{name}: unknown joint {jn!r} in set")
            new[NAMES.index(jn)] = max(-125.0, min(125.0, float(val)))          # a joint set outright: not scaled by amount
        new = [int(round(a)) for a in new]
        deg = max(abs(a - b) for a, b in zip(new, cur))
        delay = int(round(delay_s / 0.05))
        n = nominal_s(deg, speed, delay)
        total += n
        plan.append({"name": name, "frame": list(new), "speed": speed, "delay": delay, "deg": round(deg, 1), "nominal_s": round(n, 2)})
        cur = [float(a) for a in new]
    if total > MAX_NOMINAL_S:
        raise ValueError(f"the script takes about {total:.1f} s by the firmware's own stepping, more than the {MAX_NOMINAL_S:.0f} s the link stays silent")
    return plan


def load_script(name: str) -> dict:
    if not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("a script name is letters, digits, - and _")
    with open(os.path.join(SCRIPT_DIR, name + ".json")) as f:
        return json.load(f)


def main(argv: list | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Play a scripted skill on G2: the person's go first; the voice service stopped.")
    ap.add_argument("script", nargs="?", help="the script's name (pi_pipeline/behavior/scripts/NAME.json)")
    ap.add_argument("--list", action="store_true", help="list the scripts and the committed poses, touch nothing")
    ap.add_argument("--amount", type=float, default=0.3)
    ap.add_argument("--pick-gap", type=float, default=0.0, metavar="SECONDS", help="with --pick: wait this long after pickF reports its end before the script is read and sent (0 to 3; tests whether the board needs a moment before it takes the script)")
    ap.add_argument("--attention", action="store_true", help="play from the attention pose")
    ap.add_argument("--set", action="append", default=None, metavar="FRAME.JOINT=ANGLE", help="override one joint of one frame for this run, for example lunge.jaw=30 (the release time knob of the catapult)")
    ap.add_argument("--pick", action="store_true", help="play Petoi's pickF first (the object put in front of him) and the script from where it ended")
    ap.add_argument("--gyro-off", action="store_true", help="switch the firmware gyro balance off for this run (the stand-up and the script play without it)")
    ap.add_argument("--from-rest", action="store_true", help="play from the rest pose: no stand-up (a script written from rest with the pose editor's start --from-rest)")
    ap.add_argument("--watch", type=float, default=None, help="seconds the body is watched after the send (default: the stepping time of the frames times 2.6 (the stepping leaves out the servo write time: measured on G2, where the lunge came about 2 s after the send for 0.66 s of stepping) plus their pauses plus 0.6 s, so the rest command follows at once and never cuts the movement off)")
    ap.add_argument("--floor", default=None)
    ap.add_argument("--no-prompt", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        overrides = parse_overrides(a.set)
    except ValueError as e:
        print("refused:", e)
        return
    if a.list:
        names = sorted(n[:-5] for n in os.listdir(SCRIPT_DIR) if n.endswith(".json"))
        poses = os.path.join(SCRIPT_DIR, "poses")
        saved = sorted(n[:-5] for n in os.listdir(poses) if n.endswith(".json")) if os.path.isdir(poses) else []
        print("scripts:", ", ".join(names) or "none")
        print("poses:", ", ".join(saved) or "none")
        return
    if not a.script:
        print("refused: a script name is needed (--list shows them)")
        return
    try:
        script = load_script(a.script)
    except (OSError, ValueError) as e:
        print("refused:", e)
        return
    if a.dry_run:
        try:
            plan = build_plan(script, [0] * 8 + [20, 20, 30, 30, 30, 30, 30, 30], amount=a.amount, overrides=overrides)
        except (ValueError, OSError) as e:
            print("refused:", e)
            return
        for p in plan:
            print(f"  {p['name']:10s} lift {p['frame'][1]:4d} jaw {p['frame'][2]:4d} legs {p['frame'][8:]} speed {p['speed']:3d} delay {p['delay'] * 0.05:.2f} s  about {p['nominal_s']:.2f} s")
        return
    if a.gyro_off:
        os.environ["G2_GYRO_BALANCE"] = "0"                  # every gB the link would write becomes gb, and the stand-up does not turn it on for the rise
        os.environ["G2_STAND_GYRO"] = "0"
    from . import ball_chase as chase
    from ..link import imu_print
    from ..link.serial_link import SerialLink
    from ..power import battery
    link = SerialLink("/dev/serial0")
    link.connect()
    if a.gyro_off:
        link.send("gb", read_reply=False, settle=0.0)        # the gyro balance off, whatever state the board is in
        time.sleep(0.2)
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    if not imu_print.board_answers(link):
        print("refused: no IMU frames from the BiBoard: nothing was sent.")
        return
    robot = chase.SerialRobot(link)
    path = None
    try:
        if a.from_rest:
            chase.ensure_rest(link)
        else:
            chase._stand_if_lying(link, "kbalance")
        if a.attention and not a.from_rest:
            robot.posture = "stand"
            if robot.sit_down() == "fell":
                print("G2 fell going into the attention pose: stopping")
                return
        if a.pick:
            from .catapult import pick_up
            print("playing pickF first: the object in front of him")
            t_pick = time.monotonic()
            heard: list = []
            if not pick_up(link, seen=heard):
                print("pickF did not report its end in time: stopping before the script")
                return
            print(f"pickF reported its end after {time.monotonic() - t_pick:.1f} s; the board sent (seconds after the wait began, line): {heard}")
            if a.pick_gap > 0:
                print(f"waiting {a.pick_gap:.1f} s before the script")
                time.sleep(min(a.pick_gap, 3.0))
        base = chase.read_joints(link)
        if not base or len(base) < 16:
            print("refused: the joint angles could not be read: nothing was sent.")
            return
        try:
            plan = build_plan(script, base, amount=a.amount, overrides=overrides)
        except (ValueError, OSError) as e:
            print("refused:", e)
            return
        message = payload_message([{"frame": p["frame"], "speed": p["speed"], "delay": p["delay"]} for p in plan])
        print(f"{script.get('name', a.script)}: {len(plan)} frames, about {sum(p['nominal_s'] for p in plan):.1f} s at amount {a.amount}; hands near")
        echoes: list = []

        def _send():
            link.pop_other()                                  # only what the board says after the script went out
            link.play_data_skill(message)

        res = ast.run_skill(robot, "script_" + a.script, watch_s=a.watch if a.watch is not None else round(sum(p["nominal_s"] - p["delay"] * 0.05 for p in plan) * 2.6 + sum(p["delay"] * 0.05 for p in plan) + 0.6, 1), send=_send, expect_motion=False, pre_checks=False)
        echoes.extend(link.pop_other()[:40])
        print("the board said after the script was sent:", echoes or "nothing (no K echo: the script may not have been taken)")
        path = ast.write_log(res, {"script": a.script, "amount": a.amount, "plan": plan, "base_joints": base, "attention": a.attention, "overrides": {f"{k[0]}.{k[1]}": v for k, v in overrides.items()}, "picked_first": a.pick, "pick_gap_s": a.pick_gap, "board_after_send": echoes, "gyro_off": a.gyro_off, "pack_pct": pct, "pack_v": volts, "floor": a.floor}, log_dir=LOG_DIR)
        print(f"RESULT {a.script}: body {res['verdict']} (roll {res['max_roll_dev']} pitch {res['max_pitch_dev']} deg){'; logged ' + path if path else ''}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        try:
            link._end_quiet()                              # the link stays silent behind a data skill until a `k` echo that may not come (or 10 s) and drops the pose reads the eased lie-down makes: the movement is over, so rest starts at once (a throw was followed by ten seconds of standing before the lie-down began, and the legs sagged)
        except Exception:  # noqa: BLE001
            pass
        chase.ensure_rest(link)
    if path and not a.no_prompt:
        try:
            ast.update_log(path, {"observed": {"note": input("what did it do (Enter = skip): ").strip() or None, "time": time.strftime("%H:%M:%S")}})
        except EOFError:
            pass


if __name__ == "__main__":
    main()
