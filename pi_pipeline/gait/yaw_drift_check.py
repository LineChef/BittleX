"""How much does the firmware's yaw drift while G2 sits still? (a gyro bias check; no leg movement)

    python pi_pipeline/gait/yaw_drift_check.py --seconds 60 --log ~/g2_runs/yaw_drift_rest.csv [--stand] [--gyro-cal]

G2 rests (`d`, servos off) -- or with --stand holds `kbalance` with the firmware balance OFF -- while the 5 Hz IMU print is logged. A steady yaw change with nothing
moving is the gyro's bias, which the heading hold would read as a turn. Prints the net change, the rate from a straight-line fit, and the scatter around the fit.
--gyro-cal sends the firmware's gyro calibration (`gc`) first (G2 must be still and level). Leave G2 untouched for the whole run: handling shows up as yaw.
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


def analyze(samples):
    """samples: [(t_s, roll_rad, pitch_rad, yaw_rad)]. Returns net yaw change (deg), fitted rate (deg/s), scatter about the fit (deg, sd), roll/pitch sd (deg)."""
    n = len(samples)
    if n < 3:
        raise ValueError("need at least 3 IMU frames")
    t = [s[0] for s in samples]
    y = [math.degrees(s[3]) for s in samples]
    tm, ym = sum(t) / n, sum(y) / n
    sxx = sum((a - tm) ** 2 for a in t)
    slope = sum((a - tm) * (b - ym) for a, b in zip(t, y)) / sxx if sxx else 0.0
    resid = [b - (ym + slope * (a - tm)) for a, b in zip(t, y)]
    sd = lambda v: math.sqrt(sum((x - sum(v) / len(v)) ** 2 for x in v) / len(v))
    return dict(frames=n, seconds=t[-1] - t[0], net_deg=y[-1] - y[0], rate_deg_s=slope, scatter_deg=math.sqrt(sum(r * r for r in resid) / n),
                roll_sd_deg=sd([math.degrees(s[1]) for s in samples]), pitch_sd_deg=sd([math.degrees(s[2]) for s in samples]))


def run(lk, seconds, log_path=None, stand=False, gyro_cal=False, *, sleep=time.sleep, clock=time.monotonic):
    def tx(cmd):
        lk.send(cmd, read_reply=False, settle=0.0)

    tx("gb")                                   # firmware balance OFF: nothing should move
    sleep(0.3)
    if stand:
        tx("kbalance")
    else:
        tx("d")
    sleep(3.0)
    if gyro_cal:
        tx("gc")
        sleep(4.0)
    tx("gP")                                   # the 5 Hz IMU print
    sleep(0.5)
    samples, log = [], (open(log_path, "w") if log_path else None)
    if log:
        log.write(f"# yaw_drift_check seconds={seconds} stand={stand} gyro_cal={gyro_cal}\nt,roll,pitch,yaw\n")
    t0 = clock()
    try:
        while clock() - t0 < seconds:
            for line in lk.poll_imu():
                r = parse_imu_line(line)
                if r is None:
                    continue
                t = clock() - t0
                samples.append((t, r[0], r[1], r[2]))
                if log:
                    log.write(f"{t:.4f},{r[0]:.5f},{r[1]:.5f},{r[2]:.5f}\n")
            sleep(0.02)
    finally:
        if log:
            log.close()
        tx("gp")
        tx("d")
    return analyze(samples)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--log", default=None)
    ap.add_argument("--stand", action="store_true", help="hold kbalance (standing, balance off) instead of resting")
    ap.add_argument("--gyro-cal", action="store_true", help="send the firmware gyro calibration (gc) before logging; G2 must be still and level")
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    a = ap.parse_args()
    from link.serial_link import SerialLink
    lk = SerialLink(a.port, baud=a.baud)
    if not lk.connect():
        raise SystemExit(f"could not open {a.port} @ {a.baud}")
    try:
        r = run(lk, a.seconds, a.log, a.stand, a.gyro_cal)
    finally:
        lk.close()
    print(f"yaw drift at {'stand' if a.stand else 'rest'}{' after gyro cal' if a.gyro_cal else ''}: {r['frames']} frames over {r['seconds']:.0f} s | net {r['net_deg']:+.1f} deg | "
          f"rate {r['rate_deg_s']:+.3f} deg/s | scatter {r['scatter_deg']:.2f} deg | roll sd {r['roll_sd_deg']:.2f} pitch sd {r['pitch_sd_deg']:.2f}")


if __name__ == "__main__":
    main()
