"""Passively log G2 while he stands, to diagnose a posture wobble that develops after a few minutes.

    python pi_pipeline/gait/stand_log.py --minutes 20 --log ~/g2_runs/stand01.csv

Sends NO motion commands. It turns on the firmware's 5 Hz IMU print (`gP`), reads roll/pitch, asks for the battery voltage (`P`)
every `--volt-every` seconds, and prints a one-line summary per minute: how far roll/pitch swing (standard deviation and
peak-to-peak, in degrees), their mean (a drifting mean means the posture is slowly tilting), the strongest oscillation frequency
(the IMU only reports at 5 Hz, so anything above 2.5 Hz is not resolved) and the battery voltage. Stand G2 yourself (voice "stand up")
any time after it starts; the log shows the settle and when the wobble appears. Stop the g2-voice service first: only one process
can use the serial port. The IMU print is turned off (`gp`) when it ends."""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..", "..")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from imu_parse import parse_imu_line   # noqa: E402

IMU_HZ = 5.0


def _accel_g(line: str):
    """The (ax, ay, az) accelerometer triplet (in g) of an `ICM:`/`MCU:` line, or None. parse_imu_line leaves accel out."""
    s = line.strip()
    if s[:4] not in ("ICM:", "MCU:"):
        return None
    body = s[4:]
    try:
        nums = [float(x) for x in body.split()]
        if len(nums) != 6:
            nums = [float(body[i:i + 6]) for i in (0, 6, 12)] + [0, 0, 0]
        return nums[0], nums[1], nums[2]
    except ValueError:
        return None


def accel_tilt_deg(ax: float, ay: float, az: float):
    """(roll, pitch) in degrees from gravity alone: a tilt estimate that does not depend on the firmware's sensor fusion."""
    roll = math.degrees(math.atan2(ay, az))
    pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az)))
    return roll, pitch


def summarize(rolls_deg: list[float], pitches_deg: list[float], hz: float = IMU_HZ) -> dict:
    """One window of IMU samples -> swing, mean and strongest oscillation frequency."""
    def stats(v):
        if len(v) < 3:
            return None
        m = sum(v) / len(v)
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
        return m, sd, max(v) - min(v)

    def dominant_hz(v):
        n = len(v)
        if n < 8:
            return None
        m = sum(v) / n
        best, best_k = 0.0, None
        for k in range(1, n // 2 + 1):
            re = sum((v[i] - m) * math.cos(2 * math.pi * k * i / n) for i in range(n))
            im = sum((v[i] - m) * math.sin(2 * math.pi * k * i / n) for i in range(n))
            p = re * re + im * im
            if p > best:
                best, best_k = p, k
        return None if best_k is None else best_k * hz / n

    r, p = stats(rolls_deg), stats(pitches_deg)
    return {"n": len(rolls_deg), "roll": r, "pitch": p, "roll_hz": dominant_hz(rolls_deg), "pitch_hz": dominant_hz(pitches_deg)}


def acc_std(v):
    if len(v) < 3:
        return None
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))


def run(lk, minutes: float, log_path: str | None, volt_every: float = 15.0, *, sleep=time.sleep, clock=time.monotonic,
        out=lambda *a: print(*a, flush=True)) -> list[dict]:
    from pi_pipeline.power.battery import read_voltage

    lk.send("gP", read_reply=False, settle=0.0)
    sleep(0.5)
    log = open(log_path, "w", buffering=1) if log_path else None   # line-buffered: readable while it runs
    if log:
        log.write(f"# stand_log minutes={minutes}\nt,kind,roll_deg,pitch_deg,yaw_deg,volts,ax,ay,az,acc_roll_deg,acc_pitch_deg\n")
    rows, window_r, window_p, window_ar, window_ap, windows = 0, [], [], [], [], []
    t0 = clock(); next_min = 60.0; next_volt = 0.0; volts = None
    out("minute samples | roll mean  std  p2p | pitch mean  std  p2p | osc Hz r/p | accel-only std r/p | volts")
    try:
        while clock() - t0 < minutes * 60:
            now = clock() - t0
            if now >= next_volt:
                v = read_voltage(lk, attempts=2)
                if v is not None:
                    volts = v
                    if log:
                        log.write(f"{now:.2f},volt,,,,{v:.2f},,,,,\n")
                next_volt = now + volt_every
            for line in lk.poll_imu():
                r = parse_imu_line(line)
                if r is None:
                    continue
                roll, pitch, yaw = (math.degrees(a) for a in r[:3])
                window_r.append(roll); window_p.append(pitch); rows += 1
                acc = _accel_g(line)
                if acc is not None:
                    ar, ap = accel_tilt_deg(*acc)
                    window_ar.append(ar); window_ap.append(ap)
                if log:
                    extra = f"{acc[0]:.3f},{acc[1]:.3f},{acc[2]:.3f},{ar:.2f},{ap:.2f}" if acc is not None else ",,,,"
                    log.write(f"{clock() - t0:.3f},imu,{roll:.3f},{pitch:.3f},{yaw:.3f},,{extra}\n")
            if now >= next_min:
                s = summarize(window_r, window_p); s["minute"] = int(next_min // 60); s["volts"] = volts
                windows.append(s)
                if s["roll"] and s["pitch"]:
                    f = lambda x: "  -- " if x is None else f"{x:5.2f}"
                    out(f"{s['minute']:>5} {s['n']:>7} | {s['roll'][0]:8.2f} {s['roll'][1]:5.2f} {s['roll'][2]:5.1f} | "
                        f"{s['pitch'][0]:9.2f} {s['pitch'][1]:5.2f} {s['pitch'][2]:5.1f} | "
                        f"{f(s['roll_hz'])}/{f(s['pitch_hz'])} | {f(acc_std(window_ar))}/{f(acc_std(window_ap))} | "
                        f"{'--' if volts is None else f'{volts:.2f}'}")
                else:
                    out(f"{int(next_min // 60):>5}  no IMU data in this minute")
                window_r, window_p, window_ar, window_ap = [], [], [], []
                next_min += 60.0
            sleep(0.05)
    finally:
        if log:
            log.close()
        lk.send("gp", read_reply=False, settle=0.0)
    return windows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--log", default=None)
    ap.add_argument("--volt-every", type=float, default=15.0)
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()
    from pi_pipeline.link.serial_link import SerialLink
    lk = SerialLink(args.port, baud=args.baud, reset_wait=0.5)
    if not lk.connect():
        raise SystemExit(f"could not open {args.port} @ {args.baud}")
    try:
        run(lk, args.minutes, args.log, args.volt_every)
    finally:
        lk.close()


if __name__ == "__main__":
    main()
