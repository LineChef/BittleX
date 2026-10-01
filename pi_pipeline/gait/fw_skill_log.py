"""Run a firmware gait skill for a fixed time while logging the IMU, then rest.

For data on gaits that live in the BiBoard firmware (e.g. Petoi's carpet gait):

    python pi_pipeline/gait/fw_skill_log.py kcarpetF --seconds 10 --log ~/g2_runs/carpet_fw_run01.csv

Sequence: `gB` (firmware gyro balance on -- the firmware skills are tuned with it) ->
`kbalance` stand -> the skill token -> log roll/pitch/yaw for `--seconds` ->
`kbalance` -> rest (`d`). If |roll| or |pitch| stays past `--fall-abort-deg` for 0.3 s
(a fall) it rests immediately. The log uses the same columns run_gait.py writes
(radians), so the same analysis works on both.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from imu_parse import parse_imu_line   # noqa: E402

FALL_ABORT_S = 0.3


def run_skill(lk, token, seconds, log_path=None, fall_abort_deg=60.0, *,
              sleep=time.sleep, clock=time.monotonic) -> dict:
    """Returns {"fell": bool, "ticks": int}. `lk` needs `send(cmd, read_reply=, settle=)`
    and `poll_imu()` (what SerialLink provides)."""
    def tx(cmd):
        lk.send(cmd, read_reply=False, settle=0.0)

    tx("gB")                     # balance ON for firmware skills
    sleep(0.3)
    tx("kbalance")               # stand
    sleep(3.0)
    tx("gP")                     # start the 5 Hz IMU print
    sleep(0.5)
    log = open(log_path, "w") if log_path else None
    if log:
        log.write(f"# fw_skill_log  skill={token} seconds={seconds}\n")
        log.write("t,roll,pitch,yaw,gx,gy,gz,guard_state\n")
    fell, rows, tilt_since = False, 0, None
    tx(token)
    t0 = clock()
    try:
        while clock() - t0 < seconds:
            for line in lk.poll_imu():
                r = parse_imu_line(line)
                if r is None:
                    continue
                roll, pitch, yaw = r[0], r[1], r[2]
                if log:
                    log.write(f"{clock() - t0:.4f},{roll:.5f},{pitch:.5f},{yaw:.5f},0,0,0,ok\n")
                rows += 1
                if fall_abort_deg and max(abs(roll), abs(pitch)) > math.radians(fall_abort_deg):
                    tilt_since = tilt_since if tilt_since is not None else clock()
                    if clock() - tilt_since >= FALL_ABORT_S:
                        print(f"!! fallen (tilt {math.degrees(max(abs(roll), abs(pitch))):.0f} deg) -- resting",
                              flush=True)
                        fell = True
                        break
                else:
                    tilt_since = None
            if fell:
                break
            sleep(0.02)
    finally:
        if log:
            log.close()
        tx("gp")
        if not fell:
            tx("kbalance")
            sleep(1.0)
        tx("d")
    return {"fell": fell, "ticks": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("token", help="firmware skill token, e.g. kcarpetF")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--log", default=None)
    ap.add_argument("--fall-abort-deg", type=float, default=60.0)
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()
    from link.serial_link import SerialLink
    lk = SerialLink(args.port, baud=args.baud)
    if not lk.connect():
        raise SystemExit(f"could not open {args.port} @ {args.baud}")
    try:
        res = run_skill(lk, args.token, args.seconds, args.log, args.fall_abort_deg)
        print(f"done: {res['ticks']} IMU frames, {'FELL' if res['fell'] else 'stayed up'}"
              + (f", log -> {args.log}" if args.log else ""))
    finally:
        lk.close()


if __name__ == "__main__":
    main()
