"""Try one of the firmware's get-up moves from a fall on his side (or front), logging the IMU, and report whether it brought him upright.

One attempt per run (hardware test rounds run on the owner's reply, never on a timer):

    sudo systemctl stop g2-voice                      # the voice service holds the serial port; start it again afterwards
    python pi_pipeline/gait/getup_test.py rc          # the recover skill (krc)
    python pi_pipeline/gait/getup_test.py rl_rc       # roll over (krl), a pause, then recover (krc)
    python pi_pipeline/gait/getup_test.py droprec     # the last-ditch flail (kdropRec)
    python pi_pipeline/gait/getup_test.py rc --balance off      # with the firmware gyro balance off (what the exploration fall handler leaves)

G2 is placed on his side by hand first, on the floor, hands near; never on his back (the Pi and the BiBoard are exposed). The script reads the IMU, refuses to start
if he is already upright, sends the move, and watches for `--seconds`. Success = |roll| and |pitch| under `--upright-deg` for `--hold-s` in a row. Afterwards it sends
`kbalance` (eased from rest) if he is up, and `d` either way. Every attempt is appended to ~/g2_runs/getup_results.jsonl.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "..")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from imu_parse import parse_imu_line   # noqa: E402

SEQUENCES = {
    "rc": [("krc", 0.0)],
    "rl_rc": [("krl", 0.0), ("krc", 4.0)],                # the pause after the roll lets it finish before the recover starts
    "droprec": [("kdropRec", 0.0)],
}
START_MIN_TILT_DEG = 45.0       # below this he is not lying on a side or front: nothing to test


def _read_pose(lk, seconds, sleep, clock):
    """Median-ish latest (roll, pitch) in degrees from the IMU stream over `seconds`, or None."""
    t0, last = clock(), None
    while clock() - t0 < seconds:
        for line in lk.poll_imu():
            r = parse_imu_line(line)
            if r is not None:
                last = (math.degrees(r[0]), math.degrees(r[1]))
        sleep(0.05)
    return last


def classify(roll_deg, pitch_deg) -> str:
    if abs(roll_deg) >= abs(pitch_deg):
        return "left side" if roll_deg < 0 else "right side"
    return "nose down" if pitch_deg > 0 else "tail down"


def run_getup(lk, sequence, *, seconds=10.0, upright_deg=25.0, hold_s=1.0, balance="on", log_path=None,
              sleep=time.sleep, clock=time.monotonic) -> dict:
    """Run one get-up attempt. `lk` needs send(cmd, read_reply=, settle=) and poll_imu()."""
    def tx(cmd):
        lk.send(cmd, read_reply=False, settle=0.0)

    tx("gP")                                               # the 5 Hz IMU print
    sleep(0.5)
    start = _read_pose(lk, 1.5, sleep, clock)
    if start is None:
        return {"ok": False, "why": "no IMU data"}
    if max(abs(start[0]), abs(start[1])) < START_MIN_TILT_DEG:
        tx("gp")
        return {"ok": False, "why": f"he is upright (roll {start[0]:.0f}, pitch {start[1]:.0f} deg): put him on his side first"}
    lying = classify(*start)
    tx("gB" if balance == "on" else "gb")
    sleep(0.3)
    log = open(log_path, "w") if log_path else None
    if log:
        log.write(f"# getup_test sequence={sequence} balance={balance} start_roll={start[0]:.1f} start_pitch={start[1]:.1f} ({lying})\n")
        log.write("t,roll_deg,pitch_deg\n")
    t0 = clock()
    steps = SEQUENCES[sequence]
    sent = 0
    upright_since, up_at, max_tilt, frames = None, None, 0.0, 0
    try:
        while clock() - t0 < seconds:
            now = clock() - t0
            while sent < len(steps) and now >= steps[sent][1]:
                tx(steps[sent][0])
                sent += 1
            for line in lk.poll_imu():
                r = parse_imu_line(line)
                if r is None:
                    continue
                roll, pitch = math.degrees(r[0]), math.degrees(r[1])
                frames += 1
                max_tilt = max(max_tilt, abs(roll), abs(pitch))
                if log:
                    log.write(f"{now:.3f},{roll:.1f},{pitch:.1f}\n")
                if max(abs(roll), abs(pitch)) < upright_deg:
                    upright_since = upright_since if upright_since is not None else now
                    if now - upright_since >= hold_s and up_at is None:
                        up_at = upright_since
                else:
                    upright_since = None
            if up_at is not None:
                break
            sleep(0.05)
    finally:
        if log:
            log.close()
        tx("gp")
        if up_at is not None:
            tx("kbalance")                                 # eased out of the rest pose by the link
            sleep(1.5)
        tx("d")
    return {"ok": True, "sequence": sequence, "balance": balance, "lying": lying, "start_roll": round(start[0], 1), "start_pitch": round(start[1], 1),
            "upright": up_at is not None, "seconds_to_upright": None if up_at is None else round(up_at, 1), "max_tilt": round(max_tilt, 1), "frames": frames}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("sequence", choices=sorted(SEQUENCES))
    ap.add_argument("--balance", choices=("on", "off"), default="on")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--upright-deg", type=float, default=25.0)
    ap.add_argument("--log", default=None, help="CSV of roll and pitch during the attempt")
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args(argv)
    from link.serial_link import SerialLink
    lk = SerialLink(args.port, baud=args.baud)
    if not lk.connect():
        raise SystemExit(f"could not open {args.port} @ {args.baud} (is g2-voice stopped?)")
    try:
        res = run_getup(lk, args.sequence, seconds=args.seconds, upright_deg=args.upright_deg, balance=args.balance, log_path=args.log)
    finally:
        lk.close()
    print(json.dumps(res))
    if res.get("ok"):
        path = os.path.expanduser("~/g2_runs/getup_results.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(dict(res, t=time.strftime("%Y-%m-%d %H:%M:%S"))) + "\n")
        print("UPRIGHT in %.1f s" % res["seconds_to_upright"] if res["upright"] else f"did NOT get up (max tilt {res['max_tilt']} deg)")
    else:
        print(res["why"])


if __name__ == "__main__":
    main()
