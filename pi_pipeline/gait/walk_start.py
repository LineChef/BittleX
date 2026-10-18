"""Checks before a policy walk takes over (2026-10-18, early-stride falls on the pod payload): settle into a still stand after a firmware gait or
skill, never start while tilted, and the opt-in speed ramp-in. Split out of run_gait.py 2026-10-18 (no behaviour change); run_gait re-exports every name."""
from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, ".."), os.path.join(_HERE, "..", "..")):     # run by path like run_gait.py: siblings, `link`, the repo root
    if _p not in sys.path:
        sys.path.insert(0, _p)

import time

from imu_parse import parse_imu_line                          # noqa: E402


START_TILT_MAX_DEG = 30.0       # a walk never starts with more tilt than this (2026-10-18: a walk was started while G2 lay upside down, roll 161 deg at its first sample)
SETTLE_MAX_S = 2.0              # after a firmware gait or skill: how long to wait for the body to stop swaying before the walk takes over
_SETTLED_DEG = 1.0             # 5 IMU frames (1 s) within this spread of roll and pitch = still
_DOWN_POSES = ("", "d", "krest", "kzz", "ksit")


def pre_walk(send, poll_imu, last_motion_command, *, sleep=time.sleep, clock=time.monotonic, settle_max_s=SETTLE_MAX_S, tilt_max_deg=START_TILT_MAX_DEG, balance_off=True):
    """Checks before a policy walk takes the legs (2026-10-18, early-stride falls on the pod payload).
    1. If the last leg command was a firmware gait or skill (a turn, `kwkR`, a trick), the legs are mid-stride in an unknown pose: settle into `kbalance` first and wait
       until the IMU shows the body is still (up to `settle_max_s`), so the walk starts from a known, steady stand instead of jumping there while balance is switched off.
    2. If G2 is tilted past `tilt_max_deg` (lying, fallen), the walk does not start: raises SystemExit (the caller logs "could not start").
    Returns what was done, for the log. `send(cmd)` and `poll_imu()` are the link's."""
    last = (last_motion_command or "").strip()
    handoff = last.startswith("k") and last not in ("kbalance", "kup") + _DOWN_POSES
    send("gP")                                             # the 5 Hz IMU print (harmless if already on)
    if handoff:
        send("kbalance")
        if balance_off:
            send("gb")                                     # firmware balance off for the settle (the walk turns it off anyway): with it on, the 5 Hz balance loop twitched him for the whole 2 s and he never settled (exploration, 2026-10-18)
    frames: list = []
    t0 = clock()
    limit = settle_max_s if handoff else 1.0
    while clock() - t0 < limit:
        for line in poll_imu():
            r = parse_imu_line(line)
            if r is not None:
                frames.append((math.degrees(r[0]), math.degrees(r[1])))
        if frames and max(abs(frames[-1][0]), abs(frames[-1][1])) > tilt_max_deg:
            send("d")
            raise SystemExit(f"not upright at the start (roll {frames[-1][0]:.0f}, pitch {frames[-1][1]:.0f} deg): the walk did not start")
        if not handoff and frames:
            break
        if handoff and len(frames) >= 5:
            w = frames[-5:]
            if max(x for x, _ in w) - min(x for x, _ in w) <= _SETTLED_DEG and max(y for _, y in w) - min(y for _, y in w) <= _SETTLED_DEG:
                break
        sleep(0.05)
    return {"handoff": handoff, "frames": len(frames), "settle_s": round(clock() - t0, 2)}


def cmd_ramp_factor(t, ramp_s, start=0.4):
    """The share of the commanded speed at `t` seconds into a walk: from `start` up to 1 over `ramp_s` (0 = off, always 1). Sim check 2026-10-18 (100 episodes, flat, pod payload):
    no falls either way, mean early roll 6.1 vs 6.6 deg, worst 13.5 vs 9.5 deg, so it is opt-in (G2_WALK_RAMP_S)."""
    if ramp_s <= 0 or t >= ramp_s:
        return 1.0
    return start + (1.0 - start) * max(0.0, t) / ramp_s
