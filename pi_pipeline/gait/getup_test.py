"""Try one of the firmware's get-up moves from a fall on his side (or front), logging the IMU, and report whether it brought him upright.

One attempt per run, each move sent exactly once with no repeats (owner, 2026-10-18); hardware test rounds run on the owner's reply, never on a timer:

    sudo systemctl stop g2-voice                      # the voice service holds the serial port; start it again afterwards
    python pi_pipeline/gait/getup_test.py rc          # the recover skill (krc)
    python pi_pipeline/gait/getup_test.py rl_rc       # roll over (krl), a pause, then recover (krc)
    python pi_pipeline/gait/getup_test.py droprec     # the last-ditch flail (kdropRec)
    python pi_pipeline/gait/getup_test.py s_rc [--frame-s 0.6]     # the same leg keyframes streamed by the Pi with the HEAD PINNED STRAIGHT (also s_rl, s_rl_rc, s_droprec)
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

# The firmware's own leg keyframes for the get-up moves, decoded from InstinctBittleESP.h (rl_training/opencat-gym/reference_gait/build_skill_reference.py reads the same arrays).
# Petoi order = joints 8..15: [FLs, FRs, BRs, BLs, FLk, FRk, BRk, BLk]. The firmware also moves the head in `rl` (pan 15, tilt -40) and `dropRec` (pan 20, tilt 40) and a little in `rc`
# (pan -8, tilt -20 in its last two frames); with the AI head on, the swinging legs hit it, so the streamed variants below pin the head at 0 in every step.
KEYFRAMES = {
    "rc": [[-88, -43, 67, 100, 42, -35, 42, 42], [-83, -88, 100, 60, 42, 42, 42, 50], [18, 18, 22, 22, -14, -14, -13, -13], [18, 18, 18, 18, -14, -14, -14, -14], [15] * 8],
    "rl": [[32, 1, -2, 35, -25, 47, 45, -23], [3, -48, 51, 1, 42, 46, 40, 42], [-84, -48, 55, 90, 42, -28, 60, 42], [-84, -76, 60, 90, 42, 19, 60, 42],
           [35, 35, 35, 35, -28, -28, -28, -28], [15] * 8],
    "droprec": [[19, 19, 45, 45, -22, -22, 5, 5], [53, 19, 45, 45, -40, -22, 5, 5], [53, 43, 45, 45, -28, -31, 5, 5], [30] * 8],
}
STREAM_START = [75, 75, 75, 75, -55, -55, -55, -55]      # the rest pose in the same order
STREAM_STEPS_PER_S = 20


def stream_commands(name, frame_s=1.0, hold_s=0.2):
    """The `i` commands (the head, joint 0, pinned at 0) that move the legs through the firmware's keyframes for `name` ('rc', 'rl', 'droprec'),
    as [(seconds_from_start, command)], plus the total length in seconds. Each frame is reached by a linear ramp of `frame_s`, then held `hold_s`."""
    out, t, cur = [], 0.0, STREAM_START
    n = max(1, int(round(frame_s * STREAM_STEPS_PER_S)))
    for frame in KEYFRAMES[name]:
        for k in range(1, n + 1):
            pose = [round(a + (b - a) * k / n) for a, b in zip(cur, frame)]
            out.append((t + k * frame_s / n, "i0 0 " + " ".join(f"{8 + j} {v}" for j, v in enumerate(pose))))
        t += frame_s + hold_s
        cur = frame
    return out, t


SEQUENCES = {
    "rc": [("krc", 0.0)],
    "rl_rc": [("krl", 0.0), ("krc", 4.0)],                # the pause after the roll lets it finish before the recover starts
    "droprec": [("kdropRec", 0.0)],
}
SEQUENCES.update({"s_rc": [("stream:rc", 0.0)], "s_rl": [("stream:rl", 0.0)], "s_rl_rc": [("stream:rl", 0.0), ("stream:rc", 0.0)], "s_droprec": [("stream:droprec", 0.0)]})
START_MIN_TILT_DEG = 45.0       # below this he is not lying on a side or front: nothing to test


def timeline(sequence, frame_s=1.0, hold_s=0.2, gap_s=4.0):
    """[(seconds_from_start, command)] for a sequence: firmware tokens at their time, streamed moves expanded into their `i` steps; the second move waits `gap_s` after the first."""
    out, t0 = [], 0.0
    for tok, at in SEQUENCES[sequence]:
        if tok.startswith("stream:"):
            cmds, length = stream_commands(tok.split(":", 1)[1], frame_s, hold_s)
            out += [(t0 + t, c) for t, c in cmds]
            t0 += length + gap_s
        else:
            out.append((at, tok))
    return sorted(out, key=lambda x: x[0])


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
    """Near a side lie (|roll| past about 60 deg) the Euler pitch jumps between 0 and +-180, so the roll alone says which side."""
    if abs(roll_deg) >= 60.0:
        return "left side" if roll_deg < 0 else "right side"
    return "nose down" if pitch_deg > 0 else "tail down"


def run_getup(lk, sequence, *, seconds=10.0, upright_deg=25.0, hold_s=1.0, balance="off", log_path=None, frame_s=1.0,
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
    steps = timeline(sequence, frame_s)
    if any(c.startswith("i0 ") for _t, c in steps):
        seconds = max(seconds, steps[-1][0] + 4.0)                      # a streamed move takes as long as its frames do
    sent = 0
    upright_since, up_at, max_tilt, frames = None, None, 0.0, 0
    try:
        while clock() - t0 < seconds:
            now = clock() - t0
            while sent < len(steps) and now >= steps[sent][0]:
                tx(steps[sent][1])
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
    ap.add_argument("--balance", choices=("on", "off"), default="off", help="firmware gyro balance during the attempt; off (default) so the firmware cannot run its own get-up again on top of ours")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--frame-s", type=float, default=1.0, help="streamed moves (s_rc, s_rl, s_rl_rc, s_droprec): seconds to reach each keyframe (smaller = faster)")
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
        res = run_getup(lk, args.sequence, seconds=args.seconds, upright_deg=args.upright_deg, balance=args.balance, log_path=args.log, frame_s=args.frame_s)
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
