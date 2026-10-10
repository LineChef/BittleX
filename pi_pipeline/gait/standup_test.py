"""Stand-up in isolation: no walking. Logs the IMU through the stand-up from the rest pose so the jerk can be measured, then rests.

    python pi_pipeline/gait/standup_test.py MODE [--log x.csv]       MODE: old | ease | kup | ramp:SECONDS (STANDUP_STEPS_PER_S sets the step rate, default 20)

old   = the policy loops' original stand command (one `i` jump to STAND_URDF_DEG)
ease  = firmware `kbalance`, 1.5 s, then the `i` stand command (tried 2026-10-10: stood up faster than `old` and nearly fell)
ramp:T = the Pi steps the legs from the rest pose to STAND_URDF_DEG in small `i` commands over T seconds (20 steps/s)
         (the start is the firmware's rest pose, REST_URDF_DEG below, S-curve timing)

Prints peak |roll|, peak |pitch| and the yaw change through the stand-up. Stop g2-voice first (one process on the serial port). G2 starts at rest on the floor; hands near."""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, ".."), os.path.join(_HERE, "..", "..")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import deploy_map                         # noqa: E402
import run_gait as rg                     # noqa: E402
from imu_parse import parse_imu_line      # noqa: E402

from standup import REST_URDF_DEG, ramp_poses   # noqa: E402  -- the same ramp the walks use


def summarize(samples):
    """samples: [(t, roll_deg, pitch_deg, yaw_deg)] from the start of the stand-up -> (peak |roll|, peak |pitch|, yaw change)."""
    if not samples:
        return None
    pr = max(abs(s[1]) for s in samples)
    pp = max(abs(s[2]) for s in samples)
    return pr, pp, samples[-1][3] - samples[0][3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode")
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--hold", type=float, default=3.0, help="seconds logged after the stand-up command")
    ap.add_argument("--log", default=None)
    a = ap.parse_args()
    lk = rg._open_link(a.port, a.baud)
    samples, t0 = [], [None]

    def pump(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            for line in lk.poll_imu():
                f = parse_imu_line(line)
                if f is not None and t0[0] is not None:
                    samples.append((time.monotonic() - t0[0], math.degrees(f[0]), math.degrees(f[1]), math.degrees(f[2])))
            time.sleep(0.005)

    try:
        rg._send(lk, "gb"); time.sleep(0.2)
        rg._send(lk, "gP"); time.sleep(0.3)
        pump(0.5)
        t0[0] = time.monotonic()
        stand = rg.STAND_URDF_DEG
        if a.mode == "old":
            rg._send(lk, deploy_map.policy_deg_to_move_cmd(stand))
        elif a.mode == "ease":
            rg._send(lk, "kbalance"); pump(1.5)
            rg._send(lk, deploy_map.policy_deg_to_move_cmd(stand))
        elif a.mode == "kup":
            rg._send(lk, "kup")               # the scripted stand-up (the firmware skill), timed by the IMU
        elif a.mode.startswith("ramp:"):
            sps = float(os.environ.get("STANDUP_STEPS_PER_S", "20"))
            for pose in ramp_poses(REST_URDF_DEG, stand, float(a.mode.split(":")[1]), sps):
                rg._send(lk, deploy_map.policy_deg_to_move_cmd([int(round(x)) for x in pose])); pump(1.0 / sps)
        else:
            raise SystemExit("mode: old | ease | kup | ramp:SECONDS")
        pump(a.hold)
    finally:
        rg._send(lk, "gB"); time.sleep(0.2)
        rg._send(lk, "d"); time.sleep(0.5)
        rg._send(lk, "gp")
    other = lk.pop_other()
    if other:
        print(f"board lines during the stand-up ({len(other)}): {other[:8]}")
    res = summarize(samples)
    if a.log:
        with open(a.log, "w") as f:
            f.write("t,roll,pitch,yaw\n")
            f.writelines("%.3f,%.2f,%.2f,%.2f\n" % s for s in samples)
    print(f"mode {a.mode}: {len(samples)} IMU frames; peak |roll| %.1f deg, peak |pitch| %.1f deg, yaw change %.1f deg" % res if res else "no IMU frames")


if __name__ == "__main__":
    main()
