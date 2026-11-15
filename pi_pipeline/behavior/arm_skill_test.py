"""One arm skill, played on G2 with the body watched (hardware test, docs/hardware/arm-skills.md).

Runs ONLY on the owner's go, G2 on the floor on his feet, hands near, the voice service stopped (`g2armskill`). One skill per run, so the owner decides before each one. It stands him up the
standard way, reads the tilt, sends the skill token, watches the IMU for `watch_s` seconds, sends `gb` (firmware gyro balance off, after every skill, never next to a firmware gait), reads the tilt
again, lays him in rest, and writes one JSON line of what the body did to `~/g2_runs/arm_skills/`.

A tilt of `LEAN_DEG` or more from where he stood is a lean, `TIPPED_DEG` or more is a tip (the owner stops the block there), a fall is a fall. Only the arm's skills are accepted; the 20 firmware
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
# the skill tokens in the order of the test plan, mildest first. tossL and tossR are NOT separate skills in the arm firmware: the lookup matches the first table entry that starts with "toss" (the
# generic `toss`), so both play the same motion (docs/hardware/arm-skills.md).
ORDER = ("launch", "toss", "tossF", "tossL", "tossR", "hunt", "showOff")
EXTRA = ("clap",)
LOG_DIR = "~/g2_runs/arm_skills"


def verdict(max_dev_deg: float, fell: bool) -> str:
    if fell:
        return "fell"
    if max_dev_deg >= TIPPED_DEG:
        return "tipped"
    if max_dev_deg >= LEAN_DEG:
        return "lean"
    return "ok"


def run_skill(robot, token: str, *, watch_s: float = WATCH_S, say=print, sleep=time.sleep, clock=time.monotonic) -> dict:
    """Play `token` (no `k`) from a stand and report what the body did. Never raises."""
    res = {"skill": token, "verdict": "error", "max_roll_dev": None, "max_pitch_dev": None, "fell": False, "tilt_before": None, "tilt_after": None, "seconds": watch_s}
    try:
        if robot._tilt(1.5) is None:
            say("no IMU frames from the board: is the BiBoard powered on? Nothing was sent.")
            res["verdict"] = "no_board"
            return res
        if robot.stand_up() == "fell":
            res.update(verdict="fell", fell=True)
            return res
        base = robot._tilt()
        res["tilt_before"] = base
        robot._tx("gP")
        robot._pitch, robot._roll = [], []
        say(f"sending k{token}: hands near")
        robot._lk.send("k" + token, read_reply=False, settle=0.0)
        t0 = clock()
        fell = False
        while clock() - t0 < watch_s:
            if robot._fell():
                fell = True
                break
            sleep(0.05)
        robot._tx("gb")
        sleep(1.0)
        robot._fell()
        after = robot._tilt()
        res["tilt_after"] = after
        b = base or (0.0, 0.0)
        rolls = [abs(r - b[1]) for r in robot._roll] or [0.0]
        pitches = [abs(p - b[0]) for p in robot._pitch] or [0.0]
        res["max_roll_dev"], res["max_pitch_dev"] = round(max(rolls), 1), round(max(pitches), 1)
        res["fell"] = fell
        res["verdict"] = verdict(max(rolls + pitches), fell)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("g2.arm_skill_test").exception("the arm skill test failed")
    return res


def write_log(res: dict, extra: dict | None = None) -> str | None:
    try:
        d = os.path.expanduser(LOG_DIR)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, time.strftime("%Y%m%d_%H%M%S") + "_" + res["skill"] + ".json")
        with open(path, "w") as f:
            json.dump({**res, **(extra or {}), "time": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=1)
        return path
    except OSError:
        return None


def main() -> None:
    import argparse

    from . import ball_chase as chase
    ap = argparse.ArgumentParser(description="Play ONE arm skill on G2 and watch the body. Needs the owner's go; the voice service stopped.")
    ap.add_argument("--skill", required=True, help="one of: " + ", ".join(ORDER + EXTRA))
    ap.add_argument("--watch", type=float, default=WATCH_S, help="seconds to watch the IMU after the skill starts")
    ap.add_argument("--allow-clap", action="store_true", help="allow clap (large left-right leg asymmetry)")
    args = ap.parse_args()
    token = args.skill.strip()
    if token not in ORDER + EXTRA or (token in EXTRA and not args.allow_clap):
        print(f"refused: {token!r} is not an allowed arm skill (allowed: {', '.join(ORDER)}; clap needs --allow-clap)")
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
    try:
        chase._stand_if_lying(link, "kbalance")
        res = run_skill(robot, token, watch_s=args.watch)
        path = write_log(res, {"pack_pct": pct})
        print(f"RESULT {token}: {res['verdict']} (roll {res['max_roll_dev']} pitch {res['max_pitch_dev']} deg from where he stood){'; logged ' + path if path else ''}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        from .ball_chase import ensure_rest
        ensure_rest(link)                                              # rest confirmed with the board, as at the end of every session


if __name__ == "__main__":
    main()
