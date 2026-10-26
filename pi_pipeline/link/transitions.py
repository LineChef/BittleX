"""Eased transitions into firmware skills (user, 2026-10-18: ease every pose-to-pose move, falls cluster in transitions).

When the Pi sends a firmware skill (`k<name>`), the firmware jumps the legs from wherever they are to the skill's first frame at full servo speed, then plays the skill.
`SerialLink.send` now first steps the legs there itself, along the same S-curve as the stand-up ramp (gait/standup.py), so the firmware's jump has nothing left to cover.
The first frames come from `skill_frames.json` (decoded from the firmware's InstinctBittleESP.h by tools/gen_skill_frames.py; the Pi does not get rl_training/).

What is eased: any skill in the table, from a pose the link knows (rest, sit, balance or another posture skill it sent, a full-leg `i` pose that is being held).
What is not (left exactly as before):
  - a stop / freeze: `kbalance` / `kup` keep only the stand-up rule (eased from lying or sitting, immediate from anything else), `d` is never eased;
  - an unknown pose: after a firmware gait or a behaviour (a trick) the legs could be anywhere, so the firmware's own start is used, unless stage 2 is on
    (`G2_TRANSITION_READ_POSE=1`): the link then reads the servos' measured angles (`SerialLink.read_leg_pose`, two agreeing `f` rows, about 0.2-0.5 s) and eases
    from there; never between two gaits, and a failed or disagreeing read falls back to the firmware's start;
  - an `i` stream in progress (the policy walk, a look), i.e. the last leg command is under `STREAM_GAP_S` old: the caller owns that motion;
  - the get-up, calibration and placeholder skills in `NEVER_EASE`.
Mirroring: the firmware plays a skill whose name does not end in L or R mirrored at random (skill.h `loadBySkillName`), so the Pi cannot know which side it will use.
For such a skill the target is the mean of the frame and its mirror (identical for symmetric skills); for an asymmetric one the firmware then covers half the difference.

`G2_TRANSITION_RAMP_S` caps the ramp length in seconds (default 2.0; 0 or `off` = the old jump). The length scales with the largest joint move so that no joint
peaks above `PEAK_DEG_S` (80 deg/s), at least `MIN_S`: a 30 deg adjustment takes 0.56 s, the 82 deg move into a wave 1.5 s.
"""
from __future__ import annotations

import functools
import json
import os
import time
from pathlib import Path

FRAMES_PATH = Path(__file__).with_name("skill_frames.json")
DEFAULT_MAX_S = 2.0
MIN_S = 0.25
PEAK_DEG_S = 80.0       # the fastest any joint may move: the S-curve peaks at 1.5 x the move / the duration. 2026-10-18 on G2: the ramps into a sit (back legs) and down to rest (front legs) peaked at 125-190 deg/s and the legs jittered; the servos top out near 137 deg/s
STEPS_PER_S = 40         # position updates per second (2026-10-18: at 20 the legs moved in visible 4-8 deg jumps; the walk loop sends about 27 a second)
MIN_DELTA_DEG = 3
STREAM_GAP_S = 0.3
LEG_JOINTS = tuple(range(8, 16))                  # Petoi order [FLs, FRs, BRs, BLs, FLk, FRk, BRk, BLk]
REST = [75, 75, 75, 75, -55, -55, -55, -55]
BALANCE = [30] * 8
STOP_SKILLS = frozenset({"kbalance", "kup"})
# Fall reactions and get-ups (they start from a fall, and rc's first frame is out of range), calibration poses, the firmware's own lifted / dropped reactions,
# the flip tricks (never sent: they switch the firmware's gyro off for fast motion), and `zz` (its data is a zero placeholder).
NEVER_EASE = frozenset({"krc", "krl", "kdropRec", "kcalib", "kzero", "kzz", "kc", "kcd", "klifted", "kdropped", "kflip", "kflipD", "kflipF", "kbf", "kff", "kbx", "khds", "kpd"})


def max_seconds() -> float:
    try:
        from pi_pipeline.attachments import flag_safe
        if not flag_safe("blending"):                # the fitted attachment runs without pose-to-pose blending (BLENDING, not easing: the arm has blending back on, user 2026-10-25)
            return 0.0
    except ImportError:
        pass
    v = os.environ.get("G2_TRANSITION_RAMP_S", "").strip().lower()
    if v in ("off", "none", "false", "no"):
        return 0.0
    try:
        return max(0.0, float(v)) if v else DEFAULT_MAX_S
    except ValueError:
        return DEFAULT_MAX_S


@functools.lru_cache(maxsize=1)
def table() -> dict:
    try:
        return json.loads(FRAMES_PATH.read_text())
    except (OSError, ValueError):
        return {}


# The arm build (Bittle X+Arm firmware, docs/planned/robot-arm.md): every posture and every skill without an arm variant is played shifted (front shoulders -10, front knees +6), and the
# gaits with an `Arm` variant (wkF -> wkArmF, bkF -> bkArmF ...) play that one instead. Its rest and balance poses are in the arm profile's `poses` (measured on G2 2026-10-25).
ARM_FRONT_SHOULDER_SHIFT, ARM_FRONT_KNEE_SHIFT = -10, 6        # Petoi order [FLs, FRs, BRs, BLs, FLk, FRk, BRk, BLk]: indices 0 and 1, then 4 and 5


def _arm_poses():
    """The fitted attachment's `poses` entry (the arm), or None for the stock build and for anything unreadable."""
    try:
        from pi_pipeline.attachments import current, load_profiles
        return (load_profiles().get(current()) or {}).get("poses") or None
    except Exception:  # noqa: BLE001
        return None


def _petoi(urdf8):
    """URDF order [FLs, FLk, FRs, FRk, BRs, BRk, BLs, BLk] -> Petoi order [FLs, FRs, BRs, BLs, FLk, FRk, BRk, BLk]."""
    u = [float(x) for x in urdf8]
    return [u[0], u[2], u[4], u[6], u[1], u[3], u[5], u[7]]


def rest_pose():
    p = _arm_poses()
    return _petoi(p["rest_urdf_deg"]) if p and p.get("rest_urdf_deg") else list(REST)


def balance_pose():
    p = _arm_poses()
    return _petoi(p["balance_urdf_deg"]) if p and p.get("balance_urdf_deg") else list(BALANCE)


def _arm_shift(frame):
    f = [float(x) for x in frame]
    f[0] += ARM_FRONT_SHOULDER_SHIFT
    f[1] += ARM_FRONT_SHOULDER_SHIFT
    f[4] += ARM_FRONT_KNEE_SHIFT
    f[5] += ARM_FRONT_KNEE_SHIFT
    return f


def mirror(frame):
    """Swap left and right legs, as the firmware's Skill::mirror() does for the leg joints."""
    f = list(frame)
    return [f[1], f[0], f[3], f[2], f[5], f[4], f[7], f[6]]


def _skill(token: str):
    """(table row, mirror) for `k<name>`: mirror True / False, or None if the firmware picks at random. (None, None) if not a known skill."""
    name = token.strip()[1:]
    rows = table()
    if _arm_poses():
        return _arm_skill(name, rows)
    if name in rows:
        return rows[name], (False if name.endswith("L") else None)
    if name.endswith("R") and name[:-1] + "L" in rows:              # an R skill is its L skill mirrored
        return rows[name[:-1] + "L"], True
    return None, None


def _arm_skill(name, rows):
    """`_skill` for the arm build: the Arm variant of a gait when there is one, the arm's own rest and balance poses, and the front shift for everything else."""
    base, side = (name[:-1], name[-1]) if name[-1:] in ("F", "L", "R") else (name, "")
    for variant, mirrored in ((base + "Arm" + side, None if side != "L" else False), (base + "ArmL", True) if side == "R" else (None, None)):
        if variant and variant in rows and not (side == "R" and variant == base + "ArmR"):
            return rows[variant], (mirrored if side != "L" else False)
    row, mirrored = (rows[name], (False if name.endswith("L") else None)) if name in rows else (None, None)
    if row is None and name.endswith("R") and name[:-1] + "L" in rows:
        row, mirrored = rows[name[:-1] + "L"], True
    if row is None:
        return None, None
    row = dict(row)
    if name in ("balance", "up"):
        row["first"] = balance_pose()                               # already shifted: read off the board after a kbalance
    elif name in ("rest",):
        row["first"] = rest_pose()
    else:
        row["first"] = _arm_shift(row["first"])
    return row, mirrored


def _resolve(frame, mirrored):
    if mirrored is True:
        return mirror(frame)
    if mirrored is False:
        return list(frame)
    return [(a + b) / 2 for a, b in zip(frame, mirror(frame))]


def target(token: str):
    """The leg pose to ease into before sending `token`, or None if this skill is never eased."""
    c = token.strip()
    if not c.startswith("k") or c in NEVER_EASE or c in STOP_SKILLS:
        return None
    row, mirrored = _skill(c)
    if row is None:
        return None
    return _resolve(row["first"], mirrored)


def pose_after(command: str):
    """The leg pose (Petoi order, joints 8..15) after `command` once it has settled, or None if the link cannot know it."""
    c = (command or "").strip()
    if c in ("", "d", "kzz"):                                      # nothing yet = a fresh process, assumed lying (as gait/standup.py's start_pose)
        return rest_pose()
    if c[:1] in ("i", "m"):
        pairs = leg_pairs(c)
        return [float(pairs[j]) for j in LEG_JOINTS] if pairs and all(j in pairs for j in LEG_JOINTS) else None
    if c.startswith("k"):
        row, mirrored = _skill(c)
        if row is None or row["kind"] != "posture":
            return None                                              # a gait is mid-stride, a behaviour ends wherever its last frame and the firmware leave it
        if mirrored is None and row["first"] != mirror(row["first"]):
            return None                                              # an asymmetric posture played on an unknown side
        return _resolve(row["first"], mirrored if mirrored is not None else False)
    return None


def leg_pairs(command: str) -> dict:
    """{joint: angle} for the leg joints in an `i` / `m` command (empty if none or unparsable)."""
    try:
        nums = [int(x) for x in command.strip()[1:].replace(",", " ").split()]
    except ValueError:
        return {}
    return {j: a for j, a in zip(nums[0::2], nums[1::2]) if j in LEG_JOINTS}


# The picture poses are NOT eased (user, 2026-10-18: the bow, look up and check were too slow eased, so they play as the firmware does: no ramp, and no eased stand-up before them).
PLAIN_SKILLS = frozenset({"kbuttUp", "ksit", "kck"})


def is_plain(token: str) -> bool:
    """True if `token` is played without easing; `G2_EASE_PICTURE_POSES=1` eases them like every other skill again."""
    return token.strip() in PLAIN_SKILLS and os.environ.get("G2_EASE_PICTURE_POSES", "").strip().lower() not in ("1", "on", "true", "yes")


# Every pose plays with the firmware gyro balance ON (user, 2026-10-19: the pod swinging tipped him over in poses that ran with balance off). Not the stand / stop
# (balance on while standing idle wobbled him, 2026-10-17/18), not lying down, sleeping or calibration, and not the gaits (the callers already set balance for those).
# The stand guard turns it off again once the pose is over (gait/stand_guard.py). `G2_POSE_BALANCE=0` goes back to poses with balance off.
POSE_BALANCE_SKIP = STOP_SKILLS | frozenset({"krest", "kzz", "kzero", "kc", "kcd"})


def pose_balance(token: str) -> bool:
    """True if `token` is a pose that plays with the firmware gyro balance on (`gB` sent just before it)."""
    t = (token or "").strip()
    if not t.startswith("k") or t in POSE_BALANCE_SKIP or kind(t) == "gait":
        return False
    return os.environ.get("G2_POSE_BALANCE", "1").strip().lower() not in ("0", "off", "false", "no")
SOFT_END_SKEW = 0.75     # the sit: progress is made early and the last stretch is a slow creep (2026-10-18: the feet slipped where the back legs reach the floor)


def curve(u: float, skew: float = 1.0) -> float:
    """Smoothstep of `u ** skew`: skew 1 is the plain S-curve (as gait/standup.py); below 1 it moves early and arrives slowly."""
    v = u ** skew
    return v * v * (3 - 2 * v)


def peak_factor(skew: float = 1.0) -> float:
    """The curve's fastest speed in units of (move / duration): 1.5 for the plain S-curve."""
    return max((curve((i + 1) / 400, skew) - curve(i / 400, skew)) * 400 for i in range(400))


def skew_for(token: str) -> float:
    return SOFT_END_SKEW if token.strip() == "ksit" else 1.0


def ramp_seconds(start, end, cap=None, skew: float = 1.0) -> float:
    """How long to take from `start` to `end`: 0 if the move is under MIN_DELTA_DEG or easing is off."""
    cap = max_seconds() if cap is None else cap
    delta = max(abs(a - b) for a, b in zip(start, end))
    if cap <= 0 or delta < MIN_DELTA_DEG:
        return 0.0
    return min(cap, max(MIN_S, peak_factor(skew) * delta / PEAK_DEG_S))


def ramp_poses(start, end, seconds, steps_per_s=STEPS_PER_S, skew: float = 1.0):
    """S-curve steps from `start` to `end`, the last one exactly `end` (the same curve as gait/standup.py when skew is 1)."""
    n = max(1, int(round(seconds * steps_per_s)))
    out = []
    for i in range(1, n + 1):
        k = curve(i / n, skew)
        out.append([s + (e - s) * k for s, e in zip(start, end)])
    return out


def play(poses, write, *, steps_per_s=STEPS_PER_S, sleep=time.sleep, clock=time.monotonic) -> None:
    """Send each pose with `write(pose)` at an even rate: every step has its own deadline from the start, so a slow write or a late wake-up is made up
    by the next step instead of stretching the whole ramp (a plain sleep after each write drifted, and the legs moved unevenly)."""
    t0, dt = clock(), 1.0 / steps_per_s
    for i, pose in enumerate(poses, 1):
        write(pose)
        wait = t0 + i * dt - clock()
        if wait > 0:
            sleep(wait)


def leg_cmd(pose) -> str:
    """The `i` command that sets the eight leg joints (the head is left where it is)."""
    return "i" + " ".join(f"{j} {max(-120, min(120, int(round(a))))}" for j, a in zip(LEG_JOINTS, pose))


def read_pose_enabled() -> bool:
    """Stage 2 (`G2_TRANSITION_READ_POSE`, default off). Do not switch it on with the current firmware: `check_serial posecheck` on 2026-10-18 got no rows over the
    Pi's link (only the `f` echo) and the read request made G2 lean up to 21 deg while standing (docs/hardware/specs.md, "Servo position feedback")."""
    return os.environ.get("G2_TRANSITION_READ_POSE", "").strip().lower() in ("1", "on", "true", "yes")


def kind(token: str):
    row, _ = _skill((token or "").strip())
    return row["kind"] if row else None


def may_read_before(last_command: str, token: str) -> bool:
    """Whether the link may read the servos to ease from an unknown pose into `token`. Not between two gaits (a change of walk or turn keeps
    its rhythm; reading would stop him mid-stride), and not after a get-up or calibration skill (he may still be getting up)."""
    last = (last_command or "").strip()
    if last in NEVER_EASE or (kind(last) == "gait" and kind(token) == "gait"):
        return False
    return True


def is_stream(last_command: str, last_t, now=None) -> bool:
    """True if the last leg command was an `i` / `m` pose sent under STREAM_GAP_S ago (a walk or another streamed motion is running)."""
    if last_t is None or (last_command or "")[:1] not in ("i", "m"):
        return False
    return ((time.monotonic() if now is None else now) - last_t) < STREAM_GAP_S
