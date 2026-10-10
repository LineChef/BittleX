"""Record the raw IMU stream for a while and summarise it (user, 2026-10-10: what can be measured for the IMU speed estimate without walking).

    python -m pi_pipeline.gait.imu_capture --seconds 60 --pose rest   [--out ~/g2_runs/imu_rest.csv]
    python -m pi_pipeline.gait.imu_capture --seconds 60 --pose stand

G2 lies at rest (`--pose rest`, the default: nothing moves, so the floor is as good as the stand) or stands in the balance pose (`--pose stand`, the eased stand-up, then still). It logs every
frame (time, ax, ay, az as printed, roll, pitch, yaw) and prints the real frame rate, the mean and noise of each accel axis (the bias the speed estimator has to remove), and the noise of roll
and pitch. The numbers it needs for the ZUPT speed estimator at rest: accel bias, noise, and whether the stream really is 5 Hz. Tuning the estimator's constants itself needs real walking on the
floor against a measured distance; that is a separate capture. Stop the voice service first (it holds the serial port)."""
from __future__ import annotations

import argparse
import csv
import math
import os
import time

from .imu_parse import parse_imu_accel, parse_imu_line


def summarise(rows: list) -> dict:
    """rows: [(t, ax, ay, az, roll_deg, pitch_deg, yaw_deg)] -> rate and mean / std per channel."""
    n = len(rows)
    if n < 2:
        return {"frames": n}

    def stat(i):
        vals = [r[i] for r in rows]
        m = sum(vals) / len(vals)
        return round(m, 4), round(math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)), 4)
    span = rows[-1][0] - rows[0][0]
    out = {"frames": n, "seconds": round(span, 2), "rate_hz": round((n - 1) / span, 2) if span > 0 else None}
    for name, i in (("ax", 1), ("ay", 2), ("az", 3), ("roll_deg", 4), ("pitch_deg", 5), ("yaw_deg", 6)):
        out[name] = dict(zip(("mean", "std"), stat(i)))
    return out


def capture(poll, seconds: float, clock=time.monotonic, sleep=time.sleep) -> list:
    rows, t0 = [], clock()
    while clock() - t0 < seconds:
        for line in poll() or []:
            r, a = parse_imu_line(line), parse_imu_accel(line)
            if r is not None and a is not None:
                rows.append((round(clock() - t0, 3), a[0], a[1], a[2], math.degrees(r[0]), math.degrees(r[1]), math.degrees(r[2])))
        sleep(0.05)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--pose", choices=("rest", "stand"), default="rest")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    import subprocess
    if subprocess.run(["systemctl", "is-active", "--quiet", "g2-voice"]).returncode == 0:
        print("the voice service is running and holds the serial port: bash tools/g2_safe_stop.sh voice first")
        return 2
    from ..link.serial_link import SerialLink
    lk = SerialLink("/dev/serial0", baud=115200)
    if not lk.connect():
        print("could not open the serial port (is the voice service stopped?)")
        return 2
    try:
        lk.send("gP", read_reply=False, settle=0.0)
        lk.send("d" if a.pose == "rest" else "kbalance", read_reply=False, settle=0.0)
        time.sleep(3.0)                                              # let him settle (the eased stand-up takes about 1 s)
        lk.poll_imu()
        rows = capture(lk.poll_imu, a.seconds)
    finally:
        lk.send("d", read_reply=False, settle=0.0)
        lk.send("gp", read_reply=False, settle=0.0)
        lk.close()
    out = a.out or os.path.expanduser(f"~/g2_runs/imu_{a.pose}_{time.strftime('%H%M%S')}.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "ax", "ay", "az", "roll_deg", "pitch_deg", "yaw_deg"])
        w.writerows(rows)
    s = summarise(rows)
    print(f"{a.pose}: {s}\nlog -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
