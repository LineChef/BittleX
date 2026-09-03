"""Pi-side: run a fixed, policy-free calibration sequence on the real robot while
logging the `V` IMU stream + every joint command. The log feeds
`rl_training/opencat-gym/sysid_replay.py`, which replays the same commands
open-loop in the sim and measures the sim-to-real gap.

    python -m pi_pipeline.gait.sysid_collect --log sysid_YYYYMMDD.csv

Sequence (no policy, no IMU-in-the-loop -- pure open-loop so sim can replay it):
  1. neutral stand, 2 s                     -- settle / baseline
  2. hold each STATIC_POSES pose, 1.5 s     -- static sag under gravity + payload
                                               (torque adequacy, CoM)
  3. slow open-loop wkF, 3 cycles @ 25 Hz   -- whole-leg + body dynamic response
  4. neutral stand, 1.5 s

Put G2 on the floor on a flat, high-friction surface (a walk that goes nowhere
is fine -- we only need the IMU response to the commanded motion). For the static
poses it can be on a low cradle if you prefer to isolate servo sag from ground
contact; note which in the log header.

Robot not damaged by any of this -- every command is a normal pose within range,
and it rests (`d`) on exit.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import deploy_map                                          # noqa: E402
from run_gait import parse_imu_line, _open_link, _send, _readline   # noqa: E402

STAND = [50, 0, 50, 0, 50, 0, 50, 0]        # URDF order, deg -- matches env reset
# a few poses that load the servos differently (URDF order, deg)
STATIC_POSES = [
    [50, 0, 50, 0, 50, 0, 50, 0],           # neutral
    [70, -20, 70, -20, 70, -20, 70, -20],   # crouch (knees loaded)
    [30, 20, 30, 20, 30, 20, 30, 20],       # tall
    [60, -10, 40, 10, 60, -10, 40, 10],     # front/back asymmetric
    [50, 0, 50, 0, 70, -20, 70, -20],       # rear crouch (pitch forward)
]


def _stream_hold(lk, cmd_str, seconds, hz, imu_fmt, logf, t0):
    """Send cmd_str once, then log IMU frames for `seconds` at ~`hz`."""
    _send(lk, cmd_str)
    dt = 1.0 / hz
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        line = _readline(lk)
        p = parse_imu_line(line, imu_fmt) if line else None
        if p:
            r, pi, y, gx, gy, gz = p
            logf.write("%.4f,%.5f,%.5f,%.5f,%.5f,%.5f,%.5f,%s,%s\n" % (
                time.perf_counter() - t0, r, pi, y, gx, gy, gz,
                ",".join(str(int(v)) for v in _last_cmd_deg[0]), _phase_tag[0]))
        time.sleep(dt)


_last_cmd_deg = [STAND]
_phase_tag = ["stand"]


def _send_pose(lk, deg_urdf, tag):
    _last_cmd_deg[0] = list(deg_urdf)
    _phase_tag[0] = tag
    _send(lk, deploy_map.policy_deg_to_move_cmd(deg_urdf))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--log", required=True)
    ap.add_argument("--imu-format", default="auto")
    ap.add_argument("--hz", type=float, default=50.0, help="IMU sample rate while holding")
    ap.add_argument("--wkf-hz", type=float, default=25.0, help="open-loop wkF frame rate")
    ap.add_argument("--on-cradle", action="store_true", help="note in the header: static poses on a cradle")
    args = ap.parse_args()

    lk = _open_link(args.port, args.baud)
    logf = open(args.log, "w")
    logf.write(f"# sysid_collect  imu_fmt={args.imu_format}  static_on={'cradle' if args.on_cradle else 'floor'}\n")
    logf.write("t,roll,pitch,yaw,gx,gy,gz," + ",".join(f"j{k}" for k in range(8)) + ",phase\n")
    t0 = time.perf_counter()
    try:
        _send(lk, "g"); time.sleep(0.2)          # firmware balance OFF -- we want raw response
        _send(lk, "V"); time.sleep(0.2)          # IMU stream on

        _send_pose(lk, STAND, "stand0")
        _stream_hold(lk, deploy_map.policy_deg_to_move_cmd(STAND), 2.0, args.hz, args.imu_format, logf, t0)

        for i, pose in enumerate(STATIC_POSES):
            _send_pose(lk, pose, f"static{i}")
            _stream_hold(lk, deploy_map.policy_deg_to_move_cmd(pose), 1.5, args.hz, args.imu_format, logf, t0)

        ref = np.load(os.path.join(_HERE, "wkf_ref.npy"))     # (100,8) rad, URDF order
        dt = 1.0 / args.wkf_hz
        for c in range(3):
            for k, frame in enumerate(ref):
                deg = np.rint(np.rad2deg(frame)).astype(int)
                _send_pose(lk, deg, f"wkf_c{c}_f{k}")
                line = _readline(lk)
                p = parse_imu_line(line, args.imu_format) if line else None
                if p:
                    r, pi, y, gx, gy, gz = p
                    logf.write("%.4f,%.5f,%.5f,%.5f,%.5f,%.5f,%.5f,%s,%s\n" % (
                        time.perf_counter() - t0, r, pi, y, gx, gy, gz,
                        ",".join(str(int(v)) for v in deg), _phase_tag[0]))
                time.sleep(dt)

        _send_pose(lk, STAND, "stand1")
        _stream_hold(lk, deploy_map.policy_deg_to_move_cmd(STAND), 1.5, args.hz, args.imu_format, logf, t0)
    except KeyboardInterrupt:
        print("\n^C")
    finally:
        _send(lk, "V")          # stream off
        _send(lk, "d")          # rest
        logf.close()
        lk.close()
    print(f"wrote {args.log}")


if __name__ == "__main__":
    main()
