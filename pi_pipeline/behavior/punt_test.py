"""Dial in the punt distance by hand (user, 2026-10-26): one punch at each ball distance in a list, and you tell it what happened.

For each distance (inches from the CAMERA to the ball; the jaws are about 1 in nearer): you place the ball, press Enter, it looks and says what the finder reads (distance, direction), you press Enter
again to punch (the claw shut: `SerialRobot.punch`), and it asks how far the ball went and whether the claw hit it first. Every row goes to a CSV (default ~/g2_punt_tests.csv) so the values can be compared.
G2 stands up at the start (the plain firmware stand-up) and rests at the end, on Ctrl-C and on a fall.

    ssh -t <the Pi>        # the voice service stopped (sudo systemctl stop g2-voice), G2 in rest on the surface you want, the surface label set (python -m pi_pipeline.telemetry surface desk)
    cd ~/bittleX && source pi_pipeline/.venv/bin/activate
    PYTHONPATH=. python -m pi_pipeline.behavior.punt_test                       # 2, 3, 4, 5 in
    PYTHONPATH=. python -m pi_pipeline.behavior.punt_test --distances 2.5 3 3.5 4 4.5
    PYTHONPATH=. python -m pi_pipeline.behavior.punt_test --repeat 2             # each distance twice
"""
from __future__ import annotations

import csv
import os
import time
from typing import Callable

from ..vision.ball_finder import find_ball
from .ball_chase import PUNT_MIN_SWING_DEG


def run_tests(robot, camera, distances, *, repeat: int = 1, ask: Callable[[str], str] = input, say: Callable[[str], None] = print, csv_path: str | None = None, sleep=time.sleep) -> list:
    """The punch at each distance, `repeat` times each. Returns the rows (dicts). `ask(prompt)` answers the questions (Enter = yes / blank)."""
    rows = []
    writer = None
    fh = None
    if csv_path:
        path = os.path.expanduser(csv_path)
        new = not os.path.exists(path)
        fh = open(path, "a", newline="")
        writer = csv.DictWriter(fh, fieldnames=["time", "asked_in", "read_in", "bearing_deg", "swing_deg", "ball_went_in", "claw_hit_first", "note"])
        if new:
            writer.writeheader()
    try:
        for d in distances:
            for k in range(repeat):
                tag = f"{d:g} in" + (f" (try {k + 1} of {repeat})" if repeat > 1 else "")
                try:
                    ask(f"\n[{tag}] Put the ball {d:g} in ahead of the camera, straight ahead, then press Enter (Ctrl-C ends) ")
                except (EOFError, KeyboardInterrupt):
                    return rows
                sleep(1.0)
                jpeg = camera.look()
                ball = find_ball(jpeg) if jpeg else None
                if ball is None:
                    say("   the camera does not see the ball (too close, out of view or no picture)")
                    reading = "not seen"
                else:
                    reading = f"{ball.distance_in:.1f} in, {ball.bearing_deg:+.0f} deg"
                    say(f"   the finder reads the ball at {reading}")
                try:
                    go = ask("   Press Enter to punch, s + Enter to skip this one ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    return rows
                if go.startswith("s"):
                    continue
                state = robot.punt()
                swing = robot.swing_deg() if hasattr(robot, "swing_deg") else 0.0
                say(f"   punched: {state}, the body tilted {swing:.0f} deg" + ("  (barely moved: the lunge may not have played)" if state == "ok" and swing < PUNT_MIN_SWING_DEG else ""))
                if state == "fell":
                    say("   G2 fell: stopping")
                    rows.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "asked_in": d, "read_in": ball.distance_in if ball else "", "bearing_deg": ball.bearing_deg if ball else "", "swing_deg": round(swing, 1),
                                 "ball_went_in": "", "claw_hit_first": "", "note": "fell"})
                    break
                try:
                    went = ask("   How far did the ball go, in inches? (0 = it did not move, blank = skip) ").strip()
                    hit = ask("   Did the claw hit the ball first? (y / n / blank) ").strip().lower()
                    note = ask("   Anything else? (blank = no) ").strip()
                except (EOFError, KeyboardInterrupt):
                    return rows
                row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "asked_in": d, "read_in": round(ball.distance_in, 1) if ball else "", "bearing_deg": round(ball.bearing_deg, 1) if ball else "",
                       "swing_deg": round(swing, 1), "ball_went_in": went, "claw_hit_first": hit, "note": note}
                rows.append(row)
                if writer:
                    writer.writerow(row)
                    fh.flush()
    finally:
        if fh:
            fh.close()
    return rows


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="One punch at each ball distance, you report what happened; results go to a CSV.")
    ap.add_argument("--distances", type=float, nargs="+", default=[2.0, 3.0, 4.0, 5.0], help="inches from the camera to the ball (default 2 3 4 5)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--csv", default="~/g2_punt_tests.csv")
    ap.add_argument("--use-pick", action="store_true", help="punt with Petoi's pick skill instead of the punch (claw shut)")
    args = ap.parse_args()
    from ..config import settings
    from ..link.serial_link import SerialLink
    from ..power import battery
    from ..vision.snapshot import CameraSnapshotter
    from .ball_chase import SerialRobot, _SnapshotCamera, _stand_if_lying
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump)       # exposure balancing stays on
    try:
        _stand_if_lying(link)
        rows = run_tests(SerialRobot(link, use_pick=args.use_pick), _SnapshotCamera(cam), args.distances, repeat=args.repeat, csv_path=args.csv)
        print(f"\n{len(rows)} punches recorded in {args.csv}")
    except KeyboardInterrupt:
        print("\nended")
    finally:
        cam.close()
        link.send("krest", read_reply=False, settle=0.0)                 # rest at the end
        time.sleep(2.5)


if __name__ == "__main__":
    main()
