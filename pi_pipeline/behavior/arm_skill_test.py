"""One arm skill, played on G2 with the body watched (hardware test, docs/hardware/arm-skills.md).

Runs ONLY on the owner's go, G2 on the floor on his feet, hands near, the voice service stopped (`g2armskill`). One skill per run, so the owner decides before each one. It stands him up the
standard way, reads the tilt, sends the skill token, watches the IMU for `watch_s` seconds, sends `gb` (firmware gyro balance off, after every skill, never next to a firmware gait), reads the tilt
again, lays him in rest, and writes one JSON file of what the body did to `~/g2_runs/arm_skills/`: the verdict, the whole IMU trace (time since the skill was sent, pitch, roll) with when the body first moved and
when it tilted most, the wall-clock time the skill was sent, the pack before and after, the claw joint's angle before and after, the object, and (typed in after the run) where the object landed. `--pictures N` takes N
claw-camera pictures after the swing (off by default: whether the camera stream disturbs the IMU stream is not yet known).

A body that moved less than `MIN_MOTION_DEG` for a skill that should move it is `no_motion` (the skill probably did not run; `hunt` is exempt). A tilt of `LEAN_DEG` or more from where he stood is a lean, `TIPPED_DEG` or more is a tip (the owner stops the block there), a fall is a fall. Only the arm's skills are accepted; the 20 firmware
skills that tip G2 on the pod payload stay in `DISABLED_SKILLS` and `clap` needs `--allow-clap` (its left-right leg asymmetry is 97 deg, the wave's was 129 and flipped him).

    python -m pi_pipeline.behavior.arm_skill_test --skill launch
"""
from __future__ import annotations

import json
import os
import time

LEAN_DEG = 30.0
TIPPED_DEG = 45.0
WATCH_S = 6.0
MIN_MOTION_DEG = 3.0               # a skill that lunges or swings the arm moves the body at least this much; less means it did not run (2026-11-20: kpickF was echoed by the board, the body moved 2.6 deg and the claw never moved, and the test said ok)
QUIET_SKILLS = ("hunt",)           # a claw-only grab: the body may legitimately stay still, so a quiet body is not a failure for it
# the skill tokens in the order of the test plan, mildest first. tossL and tossR are NOT separate skills in the arm firmware: the lookup matches the first table entry that starts with "toss" (the
# generic `toss`), so both play the same motion (docs/hardware/arm-skills.md).
ORDER = ("launch", "toss", "tossF", "tossL", "tossR", "hunt", "showOff")
PICKS = ("pickF", "pickD")           # the pick skills: run with the object on the floor in front of the claw; the claw joint is read after the run (it stops part-open on an object, closes fully on nothing)
EXTRA = ("clap",)
LOG_DIR = "~/g2_runs/arm_skills"


def verdict(max_dev_deg: float, fell: bool, expect_motion: bool = False) -> str:
    if fell:
        return "fell"
    if max_dev_deg >= TIPPED_DEG:
        return "tipped"
    if max_dev_deg >= LEAN_DEG:
        return "lean"
    if expect_motion and max_dev_deg < MIN_MOTION_DEG:
        return "no_motion"                 # the skill was sent but the body hardly moved: it probably did not run
    return "ok"


ONSET_DEG = 2.0                    # the body counts as moving once pitch or roll is this far from where he stood


def trace_summary(times: list, pitches: list, rolls: list, base: tuple) -> dict:
    """The IMU frames of one skill as numbers: [[seconds since the skill was sent, pitch, roll], ...] (degrees, raw), the frame rate, when the body first moved (ONSET_DEG from where he stood) and when it
    tilted most (None for each when there were no frames or it never moved)."""
    n = min(len(times), len(pitches), len(rolls))
    out = {"imu_trace": [[round(times[i], 3), round(pitches[i], 1), round(rolls[i], 1)] for i in range(n)], "frames": n, "frame_hz": None, "onset_s": None, "peak_s": None}
    if n >= 2 and times[n - 1] > times[0]:
        out["frame_hz"] = round((n - 1) / (times[n - 1] - times[0]), 1)
    devs = [max(abs(pitches[i] - base[0]), abs(rolls[i] - base[1])) for i in range(n)]
    for i, d in enumerate(devs):
        if d >= ONSET_DEG:
            out["onset_s"] = round(times[i], 3)
            break
    if devs:
        out["peak_s"] = round(times[devs.index(max(devs))], 3)
    return out


def run_skill(robot, token: str, *, watch_s: float = WATCH_S, say=print, sleep=time.sleep, clock=time.monotonic, wall=time.time, capture=None, sample_joints=None, joint_samples: int = 0, send=None, expect_motion=None, pre_checks: bool = True) -> dict:
    """Play `token` (no `k`) from a stand and report what the body did. Never raises. `sample_joints()` (with `joint_samples` > 0) reads the 16 joint angles about every 0.6 s while the skill plays and logs them as `joints_during` ([seconds, angles]): the board reports commanded angles, so this shows whether the skill commands the claw (joint 2) at all; reading them stops the IMU print, so the trace has gaps. `capture`, when given, is called once after the swing (and `gb`) and returns a list of picture records for the log. `send`, when given, is called instead of sending `k<token>` (the speed series plays a data skill this way; `token` is then only the label); `expect_motion` overrides whether a quiet body counts as `no_motion` (default: every skill but `QUIET_SKILLS`). `pre_checks` False skips the tilt reads and the stand check before the send (about 2.5 s of standing), for a scripted movement that follows the stand-up straight away."""
    res = {"skill": token, "verdict": "error", "max_roll_dev": None, "max_pitch_dev": None, "fell": False, "tilt_before": None, "tilt_after": None, "seconds": watch_s}
    base = None
    try:
        if pre_checks:
            if robot._tilt(1.5) is None:
                say("no IMU frames from the board: is the BiBoard powered on? Nothing was sent.")
                res["verdict"] = "no_board"
                return res
            if robot.stand_up() == "fell":
                res.update(verdict="fell", fell=True)
                return res
            base = robot._tilt()
            res["tilt_before"] = base
        robot._tx("gP")                                         # (pre_checks False: the caller has just stood him up and checked the board, and every second of standing before a movement is time for the legs to sag)
        robot._pitch, robot._roll = [], []
        say(f"sending k{token}: hands near")
        if send is not None:
            send()
        else:
            robot._lk.send("k" + token, read_reply=False, settle=0.0)
        t0 = clock()
        res["sent_at"] = round(wall(), 3)                                                    # wall clock when the token went out: lines the phone video up with the trace
        res["sent_iso"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(res["sent_at"])) + f".{int((res['sent_at'] % 1) * 1000):03d}"
        fell = False
        taken = 0
        while clock() - t0 < watch_s:
            if robot._fell():
                fell = True
                break
            if sample_joints is not None and taken < joint_samples and clock() - t0 >= taken * 0.6:
                taken += 1
                res.setdefault("joints_during", []).append([round(clock() - t0, 2), sample_joints()])
            sleep(0.05)
        allowed = getattr(robot._lk, "_gyro_allowed", None)
        if allowed is None or not allowed():
            robot._tx("gb")                                                                  # only where the gyro runs off (the firmware default is on everywhere but a learned walk)
        sleep(1.0)
        robot._fell()
        after = robot._tilt()
        res["tilt_after"] = after
        b = base or (0.0, 0.0)
        rolls = [abs(r - b[1]) for r in robot._roll] or [0.0]
        pitches = [abs(p - b[0]) for p in robot._pitch] or [0.0]
        res["max_roll_dev"], res["max_pitch_dev"] = round(max(rolls), 1), round(max(pitches), 1)
        res["fell"] = fell
        res["verdict"] = verdict(max(rolls + pitches), fell, expect_motion=(token not in QUIET_SKILLS) if expect_motion is None else expect_motion)
        stamps = list(getattr(robot, "_imu_t", []))[-len(robot._roll):] if robot._roll else []
        if len(stamps) != len(robot._roll):                                                  # a robot without frame times: spread the frames evenly over the watch
            n = len(robot._roll)
            stamps = [t0 + watch_s * (i + 1) / n for i in range(n)]
        res.update(trace_summary([t - t0 for t in stamps], list(robot._pitch), list(robot._roll), b))
        if capture is not None:
            res["pictures"] = capture()
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("g2.arm_skill_test").exception("the arm skill test failed")
    return res


def write_log(res: dict, extra: dict | None = None, log_dir: str | None = None) -> str | None:
    try:
        d = os.path.expanduser(log_dir or LOG_DIR)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, time.strftime("%Y%m%d_%H%M%S") + "_" + res["skill"] + ".json")
        with open(path, "w") as f:
            json.dump({**res, **(extra or {}), "time": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=1)
        return path
    except OSError:
        return None


def update_log(path: str, extra: dict) -> bool:
    """Add fields (the typed landing record) to a log file already written."""
    try:
        with open(path) as f:
            data = json.load(f)
        data.update(extra)
        with open(path, "w") as f:
            json.dump(data, f, indent=1)
        return True
    except (OSError, ValueError):
        return False


def ask_landing(ask=input) -> dict:
    """The landing record, typed in after the run (inches; Enter skips a question)."""
    def num(prompt):
        try:
            return float(ask(prompt).strip())
        except (ValueError, EOFError):
            return None
    out = {"landed_in": num("how far did the object land from G2's front, inches (Enter = unknown / did not leave): ")}
    try:
        out["direction"] = ask("direction (left / right / straight / other, Enter = skip): ").strip() or None
        out["left_claw"] = {"y": True, "n": False}.get(ask("did the object leave the claw (y/n, Enter = skip): ").strip().lower()[:1])
        out["note"] = ask("note (Enter = none): ").strip() or None
    except EOFError:
        pass
    return out


def main() -> None:
    import argparse

    from . import ball_chase as chase
    ap = argparse.ArgumentParser(description="Play ONE arm skill on G2 and watch the body. Needs the owner's go; the voice service stopped.")
    ap.add_argument("--skill", required=True, help="one of: " + ", ".join(ORDER + PICKS + EXTRA))
    ap.add_argument("--watch", type=float, default=WATCH_S, help="seconds to watch the IMU after the skill starts")
    ap.add_argument("--allow-clap", action="store_true", help="allow clap (large left-right leg asymmetry)")
    ap.add_argument("--object", default=None, help="what is in the claw (a name; leave out for an empty claw)")
    ap.add_argument("--object-oz", type=float, default=None, help="the object's weight in ounces")
    ap.add_argument("--object-in", type=float, default=None, help="the object's width in inches")
    ap.add_argument("--floor", default=None, help="the floor label for this run (as set with g2floor)")
    ap.add_argument("--pictures", type=int, default=0, help="claw-camera pictures to take after the swing (default 0: camera off during the first runs)")
    ap.add_argument("--joints", type=int, default=0, help="read the joint angles this many times while the skill plays (about every 0.6 s): shows whether the skill commands the claw; the IMU trace gets gaps")
    ap.add_argument("--no-prompt", action="store_true", help="do not ask for the landing record after the run")
    args = ap.parse_args()
    token = args.skill.strip()
    if token not in ORDER + PICKS + EXTRA or (token in EXTRA and not args.allow_clap):
        print(f"refused: {token!r} is not an allowed arm skill (allowed: {', '.join(ORDER + PICKS)}; clap needs --allow-clap)")
        return
    from ..link.opencat import DISABLED_SKILLS
    if "k" + token in DISABLED_SKILLS:
        print(f"refused: k{token} is in DISABLED_SKILLS")
        return
    from ..link.serial_link import SerialLink
    from ..power import battery
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    from ..link import imu_print
    if not imu_print.board_answers(link):
        print("refused: no IMU frames from the BiBoard: is it powered on? Nothing was sent.")
        return
    robot = chase.SerialRobot(link)
    capture, cam = None, None
    if args.pictures > 0:
        from ..config import settings
        from ..vision.snapshot import CameraSnapshotter
        cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump, click=False)
        outdir = os.path.expanduser(time.strftime("~/g2_runs/arm_skills/pics_%Y%m%d_%H%M%S_") + token)

        def capture():
            os.makedirs(outdir, exist_ok=True)
            recs = []
            for i in range(args.pictures):
                try:
                    cam.discard_one()
                    time.sleep(1.0)
                    snap = cam.snapshot()
                except Exception:  # noqa: BLE001
                    snap = None
                if snap is None:
                    recs.append({"n": i + 1, "file": None, "detections": []})
                    continue
                fn = os.path.join(outdir, f"pic_{i + 1:02d}.jpg")
                try:
                    with open(fn, "wb") as f:
                        f.write(snap.jpeg)
                except OSError:
                    fn = None
                recs.append({"n": i + 1, "file": fn, "detections": [[d[0], round(float(d[1]), 2), round(float(d[2]), 3), round(float(d[3]), 3), round(float(d[4]), 3), round(float(d[5]), 3)] for d in snap.detections]})
            return recs
    path = None
    try:
        joints_before = chase.read_joints(link)                         # the claw is joint 2: read before he stands, to catch a claw left partly open
        chase._stand_if_lying(link, "kbalance")
        res = run_skill(robot, token, watch_s=args.watch, capture=capture, sample_joints=(lambda: chase.read_joints(link, timeout_s=0.6)) if args.joints > 0 else None, joint_samples=args.joints)
        volts_after = battery.read_voltage(link)
        meta = {"pack_pct": pct, "pack_v": volts, "pack_pct_after": battery.pack_percent(volts_after) if volts_after else None, "pack_v_after": volts_after, "object": args.object,
                "object_oz": args.object_oz, "object_in": args.object_in, "floor": args.floor, "claw_joint_before": joints_before[2] if joints_before and len(joints_before) > 2 else None,
                "joints_before": joints_before}
        path = write_log(res, meta)
        print(f"RESULT {token}: {res['verdict']} (roll {res['max_roll_dev']} pitch {res['max_pitch_dev']} deg from where he stood){'; logged ' + path if path else ''}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        from .ball_chase import ensure_rest
        ensure_rest(link)                                              # rest confirmed with the board, as at the end of every session
    if path:
        after = chase.read_joints(link)                                 # the claw (joint 2) after the run, G2 in rest: part-open = something held, fully closed = nothing
        update_log(path, {"claw_joint_after": after[2] if after and len(after) > 2 else None, "joints_after": after})
        if not args.no_prompt:
            update_log(path, {"landing": ask_landing()})


if __name__ == "__main__":
    main()
