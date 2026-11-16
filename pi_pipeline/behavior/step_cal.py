"""Step calibration (hardware test, 2026-11-16): how far G2 really moves in a timed step, for the small steps closer and for the long walk.

The chase times its approach with no feedback: a small step closer is NUDGE_IN_PER_S inches per second (a rough 2.8, from 8 logged nudges) and a long walk is the pace in `chase_pace` (4.2 in/s after a 1.0 s start,
a number the logged walks do not agree with). This test measures them. G2 stands with the ball in front of him; for each trial the camera reads the ball's distance and bearing, he takes one timed step, the
camera reads it again after he settles, and the FORWARD distance he covered is the ball's distance times the cosine of its bearing, before minus after. Small steps (`kwkF` scripted, the steps the nudges use)
and long walks (the chase's own `walk`) are run in a fixed order, a few of each duration. Numbers only: no picture is saved.

If the ball gets too close for the next step he backs up and reads it again. A fall, a lost ball, a ball too close to back away from, or the stop file ends it; he is laid in rest at the end.

The summary gives, per kind: the median forward inches for each duration, and a straight-line fit (inches = rate x (seconds - start)) with its spread, and the constants these suggest. Runs ONLY on the owner's go,
G2 on the floor, hands near, the voice service stopped (`g2stepcal`).

    python -m pi_pipeline.behavior.step_cal [--kinds small|long|all] [--repeats N]
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time

SMALL_SECONDS = (0.4, 0.6, 0.9, 1.2)
LONG_SECONDS = (1.5, 2.0, 3.0)
SAFE_IN = 4.5                      # the ball must still be this far from the camera after the step (closer, the camera cannot see it and the claw touches it)
MAX_READ_IN = 36.0                 # the colour finder is only tested to this distance
GUESS_RATE = {"small": 3.5, "long": 8.0}   # generous inches per second, only to decide whether there is room for the step (the measurement replaces them)
SETTLE_S = 1.5
MAX_BACKUPS = 4
STOP_FILE = "~/.local/share/g2/stepcal_stop"


def forward_in(distance_in: float, bearing_deg: float) -> float:
    """How far ahead of the camera the ball is: its distance times the cosine of its bearing."""
    return distance_in * math.cos(math.radians(bearing_deg))


def fit_line(points: list) -> dict | None:
    """Straight-line fit of inches = rate x (seconds - start) over (seconds, inches) points: needs 3 points over at least two different durations. Returns rate, start, the spread of the residuals, n."""
    if len(points) < 3 or len({round(p[0], 2) for p in points}) < 2:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    rate = sum((x - mx) * (y - my) for x, y in points) / sxx
    icpt = my - rate * mx
    resid = [y - (icpt + rate * x) for x, y in points]
    return {"rate_in_s": round(rate, 2), "start_s": round(-icpt / rate, 2) if rate else None, "spread_in": round(statistics.pstdev(resid), 2), "n": len(points)}


def summarize(rows: list) -> dict:
    """Per kind: the median forward inches for each duration, the line fit, and the constants it suggests."""
    out = {}
    for kind in ("small", "long"):
        good = [r for r in rows if r["kind"] == kind and r.get("forward_in") is not None]
        if not good:
            continue
        by = {}
        for r in good:
            by.setdefault(r["secs"], []).append(r["forward_in"])
        medians = {s: round(statistics.median(v), 2) for s, v in sorted(by.items())}
        spread = {s: round(max(v) - min(v), 2) for s, v in sorted(by.items())}
        fit = fit_line([(r["secs"], r["forward_in"]) for r in good])
        entry = {"n": len(good), "median_forward_in": medians, "range_in": spread, "fit": fit}
        if kind == "small":
            rates = [r["forward_in"] / r["secs"] for r in good if r["secs"] >= 0.6]
            if rates:
                entry["suggest_NUDGE_IN_PER_S"] = round(statistics.median(rates), 2)
        elif fit and fit["rate_in_s"] > 0:
            entry["suggest_walk_in_s"] = fit["rate_in_s"]
            entry["suggest_WALK_START_S"] = fit["start_s"]
        out[kind] = entry
    return out


def order(kinds: str, repeats: int) -> list:
    """The trial order: the shortest first so the ball is hardly disturbed, small steps before long walks, each duration `repeats` times in a row."""
    trials = []
    if kinds in ("small", "all"):
        trials += [("small", s) for s in SMALL_SECONDS for _ in range(repeats)]
    if kinds in ("long", "all"):
        trials += [("long", s) for s in LONG_SECONDS for _ in range(repeats)]
    return trials


def run_step_cal(robot, look, trials, *, say=print, sleep=time.sleep, stopped=lambda: False) -> dict:
    """`look()` -> a BallReading (distance_in, bearing_deg) or None. Returns {"ended", "rows", "summary"}. Never raises; the caller lays him in rest."""
    from .. import focus
    res = {"ended": "error", "rows": [], "summary": {}}
    try:
        with focus.holding("step_cal", "step calibration"):
            res["ended"] = "done"
            for i, (kind, secs) in enumerate(trials, 1):
                if stopped():
                    res["ended"] = "stopped"
                    break
                r0 = look()
                backs = 0
                while r0 is not None and r0.distance_in < GUESS_RATE[kind] * secs + SAFE_IN + 1.0 and backs < MAX_BACKUPS:
                    say(f"trial {i}: the ball is {r0.distance_in:.0f} in away, too close for a {secs} s {kind} step: backing up")
                    if robot.back(1.5) == "fell":
                        res["ended"] = "fell"
                        break
                    sleep(SETTLE_S)
                    backs += 1
                    r0 = look()
                if res["ended"] == "fell":
                    break
                if r0 is None:
                    say(f"trial {i}: no ball in view before the step: stopping (put the ball about 30 in straight ahead and run again)")
                    res["ended"] = "lost"
                    break
                if r0.distance_in < GUESS_RATE[kind] * secs + SAFE_IN:
                    say(f"trial {i}: the ball is still only {r0.distance_in:.0f} in away after backing up: stopping (move the ball farther out)")
                    res["ended"] = "ball_too_close"
                    break
                state = robot.walk_scripted(secs) if kind == "small" else robot.walk(secs)
                if state == "fell":
                    res["ended"] = "fell"
                    break
                sleep(SETTLE_S)
                r1 = look()
                row = {"kind": kind, "secs": secs, "d0": round(r0.distance_in, 1), "b0": round(r0.bearing_deg, 1), "d1": None, "b1": None, "forward_in": None, "backups": backs}
                if r1 is None or r1.distance_in < 3.0:
                    say(f"trial {i}: {kind} {secs} s: the ball is gone after the step (lost or too close): stopping")
                    res["rows"].append(row)
                    res["ended"] = "lost"
                    break
                row.update(d1=round(r1.distance_in, 1), b1=round(r1.bearing_deg, 1), forward_in=round(forward_in(r0.distance_in, r0.bearing_deg) - forward_in(r1.distance_in, r1.bearing_deg), 2))
                res["rows"].append(row)
                say(f"trial {i}: {kind} {secs} s: ball {row['d0']} in {row['b0']:+.0f} deg -> {row['d1']} in {row['b1']:+.0f} deg: covered {row['forward_in']} in ahead ({row['forward_in'] / secs:.1f} in/s)")
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("g2.step_cal").exception("the step calibration failed")
        res["ended"] = "error"
    res["summary"] = summarize(res["rows"])
    for kind, e in res["summary"].items():
        say(f"{kind}: median forward inches by seconds {e['median_forward_in']} (range {e['range_in']}); fit {e['fit']}"
            + (f"; suggests NUDGE_IN_PER_S {e['suggest_NUDGE_IN_PER_S']}" if "suggest_NUDGE_IN_PER_S" in e else "")
            + (f"; suggests walk pace {e['suggest_walk_in_s']} in/s, start {e['suggest_WALK_START_S']} s" if "suggest_walk_in_s" in e else ""))
    return res


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Step calibration: time small steps and long walks against a ball in view and measure how far he really goes. G2 moves: owner's go only.")
    ap.add_argument("--kinds", choices=("small", "long", "all"), default="all")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    from ..config import settings
    from ..link import imu_print
    from ..link.serial_link import SerialLink
    from ..power import battery
    from ..vision.ball_finder import find_ball
    from ..vision.snapshot import CameraSnapshotter
    from . import ball_chase as chase
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    if not imu_print.board_answers(link):
        print("refused: no IMU frames from the BiBoard: is it powered on? Nothing was moved.")
        return
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump, click=False)  # MODE-SPECIFIC(behavior/step_cal.py, 2026-11-16): no shutter click in this look
    robot = chase.SerialRobot(link)
    stop_path = os.path.expanduser(STOP_FILE)
    if os.path.exists(stop_path):
        os.remove(stop_path)

    def look():
        cam.snapshot()                                           # the module answers with the previous request's picture: drop one
        time.sleep(0.8)
        snap = cam.snapshot()
        return None if snap is None else find_ball(snap.jpeg)
    res = None
    try:
        chase._stand_if_lying(link, "kbalance")
        print(f"gait for the long walk: {chase.default_gait()}")
        res = run_step_cal(robot, look, order(args.kinds, max(1, args.repeats)), stopped=lambda: os.path.exists(stop_path))
        print(f"RESULT: {res['ended']}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        try:
            cam.close()
        finally:
            chase.ensure_rest(link)
    if res is not None:
        path = os.path.expanduser(time.strftime("~/g2_runs/stepcal_%Y%m%d_%H%M%S.json"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"gait_long": chase.default_gait(), "rows": res["rows"], "summary": res["summary"], "ended": res["ended"]}, f, indent=1)
        print(f"SAVED: {path}")


if __name__ == "__main__":
    main()
