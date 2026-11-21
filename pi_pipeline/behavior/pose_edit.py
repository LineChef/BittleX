"""The pose editor (hardware tool; the first half of authoring a scripted movement, skill `author-movement`): the person says what a pose should look like, one change at a time, and G2 eases into it so it can be judged by eye.

Nothing is released: the servos stay on and every angle is one the editor commanded, so the numbers are exact. (Moving a limb by hand cannot be recorded: the board reports the angles it was last told to hold, not where a joint is.)
Each command is one short process, because the board keeps the pose between commands. The voice service must be stopped for the whole session (`g2poseedit start` does it, `g2poseedit end` rests G2 and starts it again).

    g2poseedit start [--attention]       stand him up (eased) and read the pose; --attention: into the attention pose (legs straight) first; --from-rest: lay him in rest and start there, no stand-up
    g2poseedit set fkn=-15 rsh+=10 ...   change joints and ease to the new pose (a few seconds): absolute `name=angle`, relative `name+=n` / `name-=n`
    g2poseedit show                      the 16 angles (named) and the tilt
    g2poseedit save NAME [--note TEXT]   keep the current pose as a keyframe: ~/g2_runs/pose_edit/poses/NAME.json
    g2poseedit load NAME                 ease to a saved pose
    g2poseedit list                      the saved poses
    g2poseedit end                       lay him in rest (the alias then starts the voice service)

Joint names (servo order): pan lift jaw (arm), then the legs fls frs brs bls (shoulders: front left, front right, back right, back left) and flk frk brk blk (the knees). Groups: fsh rsh (front and rear shoulders),
fkn rkn (front and rear knees), sh (all shoulders), kn (all knees), legs, arm (pan lift jaw). Every angle is clipped to the joint's range and one command changes a joint by `STEP_MAX_DEG` degrees at most. The legs go to
the pose at `--speed` (default 12, the ratio 1.5: a stand-up-like pace; 0 is an instant jump, allowed only with `--allow-instant`).
"""
from __future__ import annotations

import json
import os
import re
import time

from .arm_speed_test import payload_message

PAN, LIFT, JAW = 0, 1, 2
NAMES = ["pan", "lift", "jaw", "j3", "j4", "j5", "j6", "j7", "fls", "frs", "brs", "bls", "flk", "frk", "brk", "blk"]
GROUPS = {"fsh": ["fls", "frs"], "rsh": ["brs", "bls"], "fkn": ["flk", "frk"], "rkn": ["brk", "blk"], "sh": ["fls", "frs", "brs", "bls"], "kn": ["flk", "frk", "brk", "blk"],
          "legs": ["fls", "frs", "brs", "bls", "flk", "frk", "brk", "blk"], "arm": ["pan", "lift", "jaw"]}
RANGES = {"pan": (-90, 90), "lift": (0, 120), "jaw": (-100, 120)}          # the legs: -125 to 125 (the int8 skill frames clip there)
LEG_RANGE = (-125, 125)
STEP_MAX_DEG = 70.0
DEFAULT_SPEED = 12
STORE = "~/g2_runs/pose_edit"
FELL_DEG = 45.0
EDIT_RE = re.compile(r"^([a-z]+)(\+=|-=|=)(-?\d+(?:\.\d+)?)$")


def joint_range(i: int) -> tuple:
    return RANGES.get(NAMES[i], LEG_RANGE)


def parse_edits(tokens: list) -> list:
    """`["fkn=-15", "rsh+=10"]` -> [(joint index, op, value), ...] with the groups expanded. Raises ValueError for a name or an edit it does not know."""
    out = []
    for t in tokens:
        m = EDIT_RE.match(t.strip().lower())
        if not m:
            raise ValueError(f"not an edit: {t!r} (name=angle, name+=n or name-=n)")
        name, op, val = m.group(1), m.group(2), float(m.group(3))
        for n in GROUPS.get(name, [name]):
            if n not in NAMES or (n.startswith("j") and n != "jaw"):
                raise ValueError(f"unknown joint {name!r}: one of pan lift jaw fls frs brs bls flk frk brk blk, or a group {sorted(GROUPS)}")
            out.append((NAMES.index(n), op, val))
    return out


def apply_edits(base: list, edits: list) -> tuple:
    """(the new 16 angles, the list of what was clipped). A joint is clipped to its range; a change over STEP_MAX_DEG degrees from `base` raises ValueError (smaller steps, so nothing moves far at once)."""
    new, notes = [float(a) for a in base[:16]], []
    for i, op, v in edits:
        target = v if op == "=" else new[i] + v if op == "+=" else new[i] - v
        lo, hi = joint_range(i)
        if not lo <= target <= hi:
            notes.append(f"{NAMES[i]} {target:g} clipped to {min(hi, max(lo, target)):g}")
            target = min(hi, max(lo, target))
        new[i] = target
    for i in range(16):
        if abs(new[i] - base[i]) > STEP_MAX_DEG:
            raise ValueError(f"{NAMES[i]} would move {abs(new[i] - base[i]):.0f} degrees at once: at most {STEP_MAX_DEG:.0f}; take it in steps")
    return [int(round(a)) for a in new], notes


def frame_message(angles: list, speed: int, delay_raw: int = 0) -> bytes:
    """The one-frame data skill that eases every joint to `angles` at `speed`."""
    return payload_message([{"frame": [int(round(a)) for a in angles], "speed": speed, "delay": delay_raw}])


def pose_path(name: str, store: str = STORE) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name or ""):
        raise ValueError("a pose name is letters, digits, - and _ (40 at most)")
    return os.path.join(os.path.expanduser(store), "poses", name + ".json")


def save_pose(name: str, angles: list, note: str | None = None, store: str = STORE) -> str:
    path = pose_path(name, store)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"name": name, "angles": [int(round(a)) for a in angles[:16]], "note": note, "time": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=1)
    return path


def load_pose(name: str, store: str = STORE) -> list:
    with open(pose_path(name, store)) as f:
        return json.load(f)["angles"]


def list_poses(store: str = STORE) -> list:
    d = os.path.join(os.path.expanduser(store), "poses")
    try:
        return sorted(n[:-5] for n in os.listdir(d) if n.endswith(".json"))
    except OSError:
        return []


def table(angles: list) -> str:
    arm = "  ".join(f"{n} {angles[i]:4d}" for i, n in enumerate(NAMES[:3]))
    legs = "  ".join(f"{n} {angles[8 + k]:4d}" for k, n in enumerate(NAMES[8:]))
    return f"arm: {arm}\nlegs: {legs}"


def _connect():
    from . import ball_chase as chase
    from ..link.serial_link import SerialLink
    link = SerialLink("/dev/serial0")
    link.connect()
    return link, chase


def _read(link, chase):
    for _ in range(3):
        j = chase.read_joints(link)
        if j and len(j) >= 16:
            return list(j[:16])
        time.sleep(0.3)
    return None


def _move(link, chase, robot, angles: list, speed: int) -> list | None:
    """Ease to `angles` as one data skill, wait for the board to finish it, then read the pose and the tilt back. Returns the angles read, or None."""
    message = frame_message(angles, speed, 2)
    link.play_data_skill(message)
    time.sleep(1.8 if speed >= 6 else 3.0)                  # the frame's own time (a few hundred ms to about two seconds) and the pause after it
    try:
        link._end_quiet()                                    # the link keeps the port silent behind a data skill until its `k` echo or 10 s, and drops `j` reads meanwhile: the move is over, so the read-back may go
    except Exception:  # noqa: BLE001
        pass
    return _read(link, chase)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Pose editor: one command per run; the voice service stopped for the session (g2poseedit start).")
    ap.add_argument("command", choices=("start", "set", "show", "save", "load", "list", "end"))
    ap.add_argument("args", nargs="*")
    ap.add_argument("--attention", action="store_true")
    ap.add_argument("--from-rest", action="store_true", help="start: lay him in the rest pose and build the poses from there instead of standing him up first")
    ap.add_argument("--speed", type=int, default=DEFAULT_SPEED)
    ap.add_argument("--allow-instant", action="store_true")
    ap.add_argument("--note", default=None)
    ap.add_argument("--gyro-on", action="store_true", help="leave the firmware gyro balance on (by default it is off for the session: with it on the board moves the legs to level the body and the angles read are not the angles sent)")
    a = ap.parse_args()
    if not a.gyro_on:
        os.environ["G2_GYRO_BALANCE"] = "0"                  # every gB the link would write becomes gb
        os.environ["G2_STAND_GYRO"] = "0"
    if a.command == "list":
        print("saved poses:", ", ".join(list_poses()) or "none yet")
        return
    if not 0 <= a.speed <= 127 or (a.speed == 0 and not a.allow_instant):
        print("refused: --speed is 1 to 127 (0, an instant jump, needs --allow-instant)")
        return
    link, chase = _connect()
    robot = chase.SerialRobot(link)
    if not a.gyro_on and a.command != "end":
        link.send("gb", read_reply=False, settle=0.0)        # the gyro balance off, whatever state the board is in
        time.sleep(0.2)
    if a.command == "end":
        chase.ensure_rest(link)
        print("G2 laid in rest. The voice service starts again (g2poseedit in the shell does it).")
        return
    if a.command == "start":
        from ..link import imu_print
        from ..power import battery
        ok, pct, volts = battery.motion_gate(link)
        print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
        if not ok:
            return
        if not imu_print.board_answers(link):
            print("refused: no IMU frames from the BiBoard: nothing was sent.")
            return
        if a.from_rest:
            chase.ensure_rest(link)                           # the session starts from the rest pose: no stand-up, no standing time, and the poses are built up from the floor
        else:
            chase._stand_if_lying(link, "kbalance")
        if a.attention and not a.from_rest:
            robot.posture = "stand"
            if robot.sit_down() == "fell":
                print("G2 fell going into the attention pose: stopping")
                chase.ensure_rest(link)
                return
        j = _read(link, chase)
        print("session started: hands near, keep each pose short (the legs can sag after about ten seconds)")
        print(table(j) if j else "the pose could not be read")
        return
    j = _read(link, chase)
    if j is None:
        print("refused: the joint angles could not be read: nothing was sent.")
        return
    if a.command == "show":
        t = robot._tilt(0.5)
        print(table(j))
        print(f"tilt: pitch {t[0]:+.0f} roll {t[1]:+.0f}" if t else "tilt: no IMU frames")
        return
    if a.command == "save":
        if not a.args:
            print("refused: save needs a name")
            return
        print("saved", save_pose(a.args[0], j, a.note))
        print(table(j))
        return
    try:
        if a.command == "load":
            target = load_pose(a.args[0]) if a.args else None
            if target is None:
                print("refused: load needs a name")
                return
            new, notes = apply_edits(j, [(i, "=", float(target[i])) for i in range(16)])
        else:
            new, notes = apply_edits(j, parse_edits(a.args))
    except (ValueError, OSError) as e:
        print("refused:", e)
        return
    for n in notes:
        print("note:", n)
    got = _move(link, chase, robot, new, a.speed)
    t = robot._tilt(0.5)
    print(table(got or new))
    if t:
        print(f"tilt: pitch {t[0]:+.0f} roll {t[1]:+.0f}" + ("  FELL: lay him in rest (g2poseedit end)" if max(abs(t[0]), abs(t[1])) > FELL_DEG else ""))
    if got is None:
        print("could not read the pose back after the move")


if __name__ == "__main__":
    main()
