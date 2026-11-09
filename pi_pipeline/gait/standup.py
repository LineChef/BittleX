"""Eased stand-up before a walk: the Pi steps the legs from the rest pose to the policy's stand pose.

The walk loops used to send the stand pose as one `i` command from rest, which moves every leg servo at top speed and jerks G2's heading before the first step
(2026-10-10: heading change 10-12 deg in 2 of 3 stand-ups, roll up to 16 deg; a 20 s run started at 12:30 instead of 12). The firmware's `kbalance` was tried first and stood
up faster and nearly fell. Now: small `i` steps along an S-curve from the firmware's `rest` pose (InstinctBittleESP.h: shoulders 75, knees -55) to the stand pose, 20 steps/s.
Tuned on G2 with the user watching: 1.6 s and 1.2 s were too slow, `kup` slightly too fast, 0.8 s right (heading change under 0.3 deg in 7 stand-ups, no beeping).

`G2_STAND_RAMP_S` sets the duration in seconds (default 0.8; 0 or `off` = the old single jump). Standing rule (user, 2026-10-10): every stand-up uses it, no exceptions. The start pose comes
from the link's last motion command: `d` or none yet (a fresh process) = the rest pose, `kbalance` / `kup` = the balance pose, an `i...` command = the angles in it; anything else (a firmware gait
mid-stride, a skill) is unknown and is left to the firmware. Two places apply it: the walk loops (`ramp_to_stand`, from any known pose to the policy stand) and `SerialLink.send` (`kup` / `kbalance`
sent from rest, so the voice "stand up", wake-up, get-up choreography and exploration all get it). A stop / freeze `kbalance` (from a stride, an emergency) is NOT a stand-up and stays immediate.
"""
from __future__ import annotations

import os
import time

REST_URDF_DEG = [75, -55] * 4        # the firmware `rest` skill pose, URDF order [shoulder, knee] per leg (servo degrees = URDF degrees, sign +1 / offset 0)
DEFAULT_RAMP_S = 0.8
STEPS_PER_S = 20


def _poses():
    """The fitted attachment's own stand-up poses (gait_profiles.json "poses"), or None for the stock build: the arm firmware shifts every pose (front shoulders -10, front knees +6) and its
    lift servo (joint 1) rests at 59 with the claw on the floor. {"rest_urdf_deg", "balance_urdf_deg" (URDF order), "arm_rest", "arm_walk", "stand_via": "kbalance" (the plain firmware stand-up, the default) or "sequenced"}."""
    try:
        from pi_pipeline.attachments import current, load_profiles
        return (load_profiles().get(current()) or {}).get("poses") or None
    except Exception:  # noqa: BLE001 -- scripts run by path have no package; the stock poses are the safe answer
        return None


def rest_pose():
    p = _poses()
    return [float(x) for x in p["rest_urdf_deg"]] if p and p.get("rest_urdf_deg") else list(REST_URDF_DEG)


def balance_pose():
    p = _poses()
    return [float(x) for x in p["balance_urdf_deg"]] if p and p.get("balance_urdf_deg") else list(BALANCE_URDF_DEG)


def _blending_on() -> bool:
    """The fitted attachment's `blending` switch (pose-to-pose: the blend into balance at the end of a walk, and the link's blend into a skill's first frame); on when it cannot be read.
    Easing (smoothing a skill's own motion) is the separate `easing` switch (user, 2026-10-25)."""
    try:
        from pi_pipeline.attachments import flag_safe
    except ImportError:
        return True
    return flag_safe("blending")


def _easing_on() -> bool:
    """The fitted attachment's `easing` switch (the arm turns every ramp off for its first tests, user 2026-10-24); on when it cannot be read."""
    try:
        from pi_pipeline.attachments import flag_safe
    except ImportError:
        return True
    return flag_safe("easing")


def ramp_seconds() -> float:
    if not _easing_on():
        return 0.0
    v = os.environ.get("G2_STAND_RAMP_S", "").strip().lower()
    if v in ("off", "none", "false", "no"):
        return 0.0
    try:
        return max(0.0, float(v)) if v else DEFAULT_RAMP_S
    except ValueError:
        return DEFAULT_RAMP_S


SIT_TO_REST_S = 2.0          # a stand-up that starts from a sit first eases down to rest this long (SerialLink._stand_up; the front knee moves 100 deg, so 2.0 s keeps its peak near 75 deg/s), then stands up from rest


def ramp_poses(start, end, seconds, steps_per_s=STEPS_PER_S):
    """S-curve (smoothstep) steps from `start` to `end` (8 URDF angles each), the last one exactly `end`."""
    n = max(1, int(round(seconds * steps_per_s)))
    out = []
    for i in range(1, n + 1):
        u = i / n
        k = u * u * (3 - 2 * u)
        out.append([s + (e - s) * k for s, e in zip(start, end)])
    return out


BALANCE_URDF_DEG = [30, 30] * 4      # the firmware `balance` / `up` skill pose (shoulders 30, knees 30)
SIT_URDF_DEG = [45.0, 45.0, 45.0, 45.0, 105.0, -45.0, 105.0, -45.0]      # the firmware `sit` pose, decoded from InstinctBittleESP.h (reference_gait/sit_ref.npy), URDF order
_URDF_TO_SERVO = [8, 12, 9, 13, 10, 14, 11, 15]       # same table as gait/deploy_map.py (a test checks they agree); kept here so the serial link needs no numpy


def move_cmd(deg) -> str:
    """8 URDF angles -> the `i` command (same as deploy_map.policy_deg_to_move_cmd, no numpy)."""
    return "i" + " ".join(f"{_URDF_TO_SERVO[k]} {max(-120, min(120, int(round(deg[k]))))}" for k in range(8))


def start_pose(last_motion_command):
    """The leg angles (URDF order) G2 is in after `last_motion_command`, or None if unknown."""
    c = (last_motion_command or "").strip()
    if c in ("", "d", "krest", "kzz"):
        return rest_pose()
    if c in ("kbalance", "kup"):
        return balance_pose()
    if c == "ksit":
        return list(SIT_URDF_DEG)
    if c.startswith("i"):
        try:
            nums = [int(x) for x in c[1:].split()]
            pairs = dict(zip(nums[0::2], nums[1::2]))
            return [float(pairs[_URDF_TO_SERVO[k]]) for k in range(8)]
        except (ValueError, KeyError):
            return None
    return None


def ramp_to_stand(send, make_cmd, stand_deg, sleep=time.sleep, last_motion_command=None, seconds=None) -> bool:
    """Ramp from where the last command left the legs to `stand_deg`. `send(cmd)` is the caller's fire-and-forget send, `make_cmd(deg_list)` builds the `i` command.
    Returns True if the ramp ran (the caller still sends the exact stand pose afterwards)."""
    if stand_sequenced(send, sleep, last_motion_command) or stand_via_firmware(send, sleep, last_motion_command):
        last_motion_command = "kbalance"
    secs = ramp_seconds() if seconds is None else seconds
    start = start_pose(last_motion_command)
    if secs <= 0 or start is None or max(abs(a - b) for a, b in zip(start, stand_deg)) < 3:
        return False
    for pose in ramp_poses(start, stand_deg, secs):
        send(make_cmd([int(round(x)) for x in pose]))
        sleep(1.0 / STEPS_PER_S)
    return True



SEQ_REAR_S, SEQ_FRONT_S = 1.0, 1.1          # the sequenced stand-up: the rear legs rise over this long; the front legs over this long, starting while the rear is about half way
SEQ_FRONT_START_S = 0.5                     # (user, 2026-10-25: "too much time between the back legs standing up and the front legs")
SEQ_LIFT_FROM_S, SEQ_LIFT_TO_S = 0.4, 2.0   # the arm's lift servo eases from its rest angle to its walking angle inside the leg commands, while the legs rise; 1.6 s for the 60 deg (2026-10-25: over 0.8 s the pull-back was jerky, 4 to 6 deg a step at its fastest)
_REAR_URDF = (4, 5, 6, 7)                    # URDF order [FLs,FLk,FRs,FRk,BRs,BRk,BLs,BLk]: the rear legs ...
_FRONT_URDF = (0, 1, 2, 3)                   # ... and the front legs


def _smooth(u: float) -> float:
    return u * u * (3 - 2 * u)


def _ease_out(u: float) -> float:
    return 1 - (1 - u) ** 2                  # fast at the start: no dead time before the front legs get going


def stand_via(p) -> str | None:
    """How the arm stands up from rest: `G2_STAND_VIA=sequenced|kbalance` for one run, else the profile's `stand_via`. (2026-11-08: the plain firmware `kbalance` moves all eight joints at once and
    tipped him over toward the side whose legs rose later; `sequenced` is the Pi's own rear-then-front rise with both sides together.)"""
    v = os.environ.get("G2_STAND_VIA", "").strip().lower()
    if v in ("sequenced", "kbalance", "kskill"):
        return v
    return p.get("stand_via") if p else None


def use_kskill(p) -> bool:
    """Whether the stand-up from rest is the board-played `K` skill (link/kskill.py): the default since 2026-11-08 (owner: "the new eased standup looks good, lets keep it"; 10 of 10 stood, roll within 2 deg).
    `G2_STAND_VIA` (kskill | kbalance | sequenced) decides for one run, else `motion_feel.STAND_KSKILL` (1). Only where there are arm poses (the stock robot keeps its own stand-up)."""
    if not p:
        return False
    v = os.environ.get("G2_STAND_VIA", "").strip().lower()
    if v in ("sequenced", "kbalance", "kskill"):
        return v == "kskill"
    try:
        from .. import motion_feel
        return motion_feel.get("STAND_KSKILL") >= 1
    except Exception:  # noqa: BLE001
        return False


def stand_sequenced(send, sleep=time.sleep, last_motion_command=None) -> bool:
    """The arm build's stand-up in order (profile "poses": {"stand_via": "sequenced"}; 2026-10-25: the firmware kbalance moves all eight leg joints at once and G2 fell front right
    when the nose rose with the claw out ahead). From rest: the rear legs ease to the balance pose with the front paws and the claw on the floor; the front legs follow, starting when the
    rear is about half way (a fast start, no pause between them); the lift servo eases 60 -> 0 inside the same commands; no firmware `kbalance` after it (it replays the whole stand-up).
    Returns True if it ran."""
    p = _poses()
    c = (last_motion_command or "").strip()
    if not p or stand_via(p) != "sequenced" or c not in ("", "d", "krest", "kzz"):
        return False
    start, goal = rest_pose(), balance_pose()
    end_s = max(SEQ_FRONT_START_S + SEQ_FRONT_S, SEQ_LIFT_TO_S)
    n = int(round(end_s * STEPS_PER_S))
    lift0, lift1 = p.get("arm_rest"), p.get("arm_walk")
    for i in range(1, n + 1):
        t = i / STEPS_PER_S
        now = list(start)
        for group, t0, dur, curve in ((_REAR_URDF, 0.0, SEQ_REAR_S, _smooth), (_FRONT_URDF, SEQ_FRONT_START_S, SEQ_FRONT_S, _ease_out)):
            u = min(1.0, max(0.0, (t - t0) / dur))
            for k in group:
                now[k] = start[k] + (goal[k] - start[k]) * curve(u)
        cmd = move_cmd(now)
        if lift0 is not None and lift1 is not None:
            lift = lift0 + (lift1 - lift0) * _smooth(min(1.0, max(0.0, (t - SEQ_LIFT_FROM_S) / (SEQ_LIFT_TO_S - SEQ_LIFT_FROM_S))))
            cmd = f"i1 {int(round(lift))} {cmd[1:]}"          # one `i` command with the lift pair first: "i1 <lift> 8 <deg> 12 <deg> ..."
        send(cmd)
        sleep(1.0 / STEPS_PER_S)
    sleep(0.5)                                                  # NO `kbalance` here (2026-10-25, hardware): the firmware starts a skill from the posture it believes he is in (rest: it never saw these `i` moves as a skill), so it played its own whole stand-up a second time
    return True                                                 # and pulled the arm back to 60 again; the legs and the lift are already at the balance pose


SIT_REAR_S, SIT_FRONT_S, SIT_FRONT_START_S = 1.8, 1.1, 0.6      # the stand-up from a sit: the back legs rise slowly over SIT_REAR_S, the front legs (already nearly straight in a sit) follow from SIT_FRONT_START_S


def stand_from_sit(send, sleep=time.sleep, last_motion_command=None) -> bool:
    """The arm build's stand-up from a SIT (user, 2026-11-01: after the claw look he stands up slowly with the back legs). The back legs rise from the sit pose to the balance pose over SIT_REAR_S;
    the front legs, which a sit holds almost straight, follow a little later; the lift servo stays where the claw look left it (home). No firmware `kbalance` after it (the caller skips it).
    Only with the arm's profile and only from `ksit`. Returns True if it ran."""
    p = _poses()
    if not p or (last_motion_command or "").strip() != "ksit":
        return False
    start, goal = list(SIT_URDF_DEG), balance_pose()
    end_s = max(SIT_REAR_S, SIT_FRONT_START_S + SIT_FRONT_S)
    n = int(round(end_s * STEPS_PER_S))
    for i in range(1, n + 1):
        t = i / STEPS_PER_S
        now = list(start)
        for group, t0, dur in ((_REAR_URDF, 0.0, SIT_REAR_S), (_FRONT_URDF, SIT_FRONT_START_S, SIT_FRONT_S)):
            u = min(1.0, max(0.0, (t - t0) / dur))
            for k in group:
                now[k] = start[k] + (goal[k] - start[k]) * _smooth(u)
        send(move_cmd(now))
        sleep(1.0 / STEPS_PER_S)
    sleep(0.4)
    return True


ATTENTION_URDF_DEG = [0.0] * 8               # the firmware `calib` pose ("attention", legs straight): every leg joint at 0 (InstinctBittleESP.h `calib`)
ATT_SMOOTH = os.environ.get("G2_ATT_STAND", "smooth").strip().lower() != "legacy"      # (user, 2026-11-08) one smooth motion; G2_ATT_STAND=legacy keeps the two-stage stand-up
ATT_REAR_S, ATT_FRONT_S = (1.2, 1.4) if ATT_SMOOTH else (1.2, 1.5)    # the stand-up from the attention pose: the back legs rise over ATT_REAR_S, the front legs over ATT_FRONT_S (user, 2026-11-02: the all-at-once
ATT_FRONT_START_S = 0.35 if ATT_SMOOTH else ATT_REAR_S - 0.3           # firmware kbalance out of the attention pose flipped him over); the biggest joint move (a knee, about 56 deg) peaks near 70 deg/s
# (user, 2026-11-08: "the front legs should start standing up right after the back legs so the getup is one smooth motion with the front legs slightly after the back legs": the front legs now start 0.35 s
# in, when the back legs are about a fifth of the way up, and both groups finish near 1.2 and 1.75 s; the biggest knee move peaks near 60 deg/s over 1.4 s, under the 80 deg/s cap. The old timing started them
# 0.9 s in, when the back legs were 85% up, which looked like two motions.)
ATT_REFRESH_EVERY = 4 if ATT_SMOOTH else 0   # steps: every this many steps the whole leg pose (what each joint should be by now) is sent again, so a joint whose command was dropped or garbled is corrected within about
                                             # 0.3 s, not at the end (the stand-ups that fell on 2026-11-07 had a leg left folded or out backwards); about 0.2 KB/s more, still well under the 1 KB/s that dropped a byte
# (user, 2026-11-03: a little less time between the back legs and the front legs: the front legs start 0.3 s before the back legs finish, when the back legs are about 85% up)
ATT_STEPS_PER_S = 14                         # (2026-11-02: one stand-up in 13 folded the front-right leg up instead of down. Likely cause: full 8-joint `i` commands at 20 a second, about 1 KB/s,
                                             # while the board is still moving; a dropped byte turns a command into a wrong angle.) So: 10 a second, only the joints that changed, and
# (user, 2026-11-03: the front legs rising were jerky: 56 deg of knee in 1.0 s at 10 steps a second was 5 to 8 deg a step. Now 1.5 s, 14 steps a second (about 4 deg a step at the fastest), the front legs still
# after the back legs. Still only the changed joints, so about 0.5 KB/s: well under the 1 KB/s that dropped a byte on 2026-11-02.)
ATT_FINAL_REPEATS = 2                        # the whole balance pose sent again this many times at the end, after a pause, so the last angles always arrive whole


def _pairs_cmd(pairs) -> str:
    """[(servo, deg), ...] -> one `i` command with only those joints."""
    return "i" + " ".join(f"{j} {max(-120, min(120, int(round(d))))}" for j, d in pairs)


def stand_from_attention(send, sleep=time.sleep, last_motion_command=None) -> bool:
    """The stand-up from the attention pose (`kcalib`): back legs first, then the front legs (user, 2026-11-02), to the balance pose of the fitted attachment. Any build; only from
    `kcalib`. Each step sends only the joints that changed (ATT_STEPS_PER_S a second), then the full balance pose ATT_FINAL_REPEATS times. No firmware `kbalance` after it (the caller
    skips it, as for the other stand-ups here: the firmware would stand up again from the pose it believes he is in). The arm and the head are not sent. Returns True if it ran."""
    if (last_motion_command or "").strip() != "kcalib":
        return False
    start, goal = list(ATTENTION_URDF_DEG), balance_pose()
    end_s = max(ATT_REAR_S, ATT_FRONT_START_S + ATT_FRONT_S)
    n = int(round(end_s * ATT_STEPS_PER_S))
    last = [int(round(x)) for x in start]
    for i in range(1, n + 1):
        t = i / ATT_STEPS_PER_S
        changed = []
        for group, t0, dur in ((_REAR_URDF, 0.0, ATT_REAR_S), (_FRONT_URDF, ATT_FRONT_START_S, ATT_FRONT_S)):
            u = min(1.0, max(0.0, (t - t0) / dur))
            for k in group:
                d = int(round(start[k] + (goal[k] - start[k]) * _smooth(u)))
                if d != last[k]:
                    last[k] = d
                    changed.append((_URDF_TO_SERVO[k], d))
        if changed:
            send(_pairs_cmd(changed))
        if ATT_REFRESH_EVERY and i % ATT_REFRESH_EVERY == 0 and i < n:
            send(move_cmd(last))                                 # the whole pose as it should be now (see ATT_REFRESH_EVERY)
        sleep(1.0 / ATT_STEPS_PER_S)
    for _ in range(ATT_FINAL_REPEATS):
        sleep(0.25)                                              # let the board catch up first: these arrive whole
        send(move_cmd(goal))
    sleep(0.3)
    return True


def stand_via_firmware(send, sleep=time.sleep, last_motion_command=None) -> bool:
    """The arm build stands up with the plain firmware `kbalance` (profile "poses": {"stand_via": "kbalance"}), which also sets the lift servo to its walking angle (0). Used by the walk
    loops when they start from rest: the Pi never sets joint 1 itself, so a walk that began from `rest` walked with the claw reaching forward (lift 59, the claw on the floor).
    The Pi's own ramp of the lift (12 `i 1 N` at 20 per second) and an eased leg stand-up reset the BiBoard on G2 (2026-10-25), so neither is used. Returns True if it ran
    (the caller's stand command then follows, from the balance pose)."""
    p = _poses()
    c = (last_motion_command or "").strip()
    if not p or stand_via(p) != "kbalance" or c not in ("", "d", "krest", "kzz"):
        return False
    send("kbalance")
    sleep(2.0)
    return True


def walk_lift():
    """The lift-servo angle (joint 1) the fitted attachment holds while walking (profile "poses": {"walk_lift_deg": N}), or None to leave it where the firmware put it (about 0-2 after kbalance)."""
    p = _poses()
    try:
        return int(p["walk_lift_deg"]) if p and p.get("walk_lift_deg") is not None else None
    except (TypeError, ValueError):
        return None


def apply_walk_lift(send) -> bool:
    """Set the claw's carrying height for a walk: one `i1 N` after the stand-up and before the first stride (kbalance puts the lift back at the firmware's angle, so every walk start sets it).
    Nothing unless the profile sets one; a value outside the saved range is ignored (the profile is hand-edited). Never raises: a walk must not fail over the claw's height."""
    n = walk_lift()
    if n is None:
        return False
    try:
        from pi_pipeline.attachments import WALK_LIFT_RANGE
        if not WALK_LIFT_RANGE[0] <= n <= WALK_LIFT_RANGE[1]:
            return False
        send(f"i1 {n}")
        return True
    except Exception:  # noqa: BLE001
        return False


BLEND_S = 0.6


def blend_to_balance(send, make_cmd=move_cmd, sleep=time.sleep, last_motion_command=None, seconds=BLEND_S) -> bool:
    """Ease the legs from where the last command left them (often mid-stride, a foot in the air) to the balance pose before the `kbalance` token, instead of snapping there (user, 2026-10-10: exploration walks
    ended with one foot in the air and were unstable). Returns True if a blend ran; an unknown last pose (a firmware gait, a skill) is left to the firmware, as for the stand-up.
    No blend while the fitted attachment has blending off."""
    if not _blending_on():
        return False
    return ramp_to_stand(send, make_cmd, balance_pose(), sleep=sleep, last_motion_command=last_motion_command, seconds=seconds)
