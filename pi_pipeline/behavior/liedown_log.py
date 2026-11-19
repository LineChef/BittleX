"""The tilt around every lie-down (owner, 2026-11-18: the lie-down from a sagging or rolled stand flipped G2 three times in one day, and nothing recorded what the body did in the seconds after `krest`).

`trace(robot, why, before=...)` is called right after the rest command is sent. It switches the IMU print on, reads the body's (pitch, roll) for the longest checkpoint, and writes one line to
`~/.local/share/g2/liedown_events.jsonl` (`G2_LIEDOWN_LOG` moves it, `0` turns it off): why he was laid down, the tilt just before, the median tilt around each checkpoint (`G2_LIEDOWN_TIMES`, default
"1,3" seconds after `krest`), the largest tilt seen, whether he went past the fall angle, the pack voltage (live, read before the lie-down) and the floor. ONE function for every mode: the shared
`SerialRobot` lie-downs (`rest_then_stand`, a fall, a body found fallen before a move) call it. With it off the lie-down waits exactly as it did before. Never raises."""
from __future__ import annotations

import json
import logging
import math
import os
import statistics
import time
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CHECKPOINTS = (1.0, 3.0)
WINDOW_S = 0.4                    # the tilt at a checkpoint is the median of the frames within this many seconds of it


def log_path() -> str | None:
    """Where the lines go, or None when the log is switched off."""
    p = os.environ.get("G2_LIEDOWN_LOG", "~/.local/share/g2/liedown_events.jsonl").strip()
    return None if p.lower() in ("0", "off", "false", "no", "") else os.path.expanduser(p)


def checkpoints() -> tuple:
    """Seconds after the rest command at which the tilt is recorded (G2_LIEDOWN_TIMES, "1,3" by default; "1,3,10" also times the 10 s checkpoint)."""
    raw = os.environ.get("G2_LIEDOWN_TIMES", "")
    try:
        got = tuple(sorted(float(x) for x in raw.split(",") if x.strip()))
    except ValueError:
        got = ()
    return got or DEFAULT_CHECKPOINTS


def _frames(robot, t_end: float) -> list:
    """(seconds since the call, pitch deg, roll deg) from the IMU print until `t_end` seconds have passed."""
    try:
        from ..gait.imu_parse import parse_imu_line
    except ImportError:
        from gait.imu_parse import parse_imu_line  # type: ignore
    clock, sleep, lk = robot._clock, robot._sleep, robot._lk
    t0, out = clock(), []
    robot._tx("gP")
    for _ in range(int(t_end / 0.05) + 20):                      # also bounded by count: a clock that does not advance (a test's frozen one) must not hold the lie-down forever
        now = clock() - t0
        if now >= t_end:
            break
        for line in lk.poll_imu():
            r = parse_imu_line(line)
            if r is not None:
                out.append((now, math.degrees(r[1]), math.degrees(r[0])))
        sleep(0.05)
    robot._imu_release()
    return out


def _at(frames: list, checkpoint: float):
    near = [(p, r) for t, p, r in frames if abs(t - checkpoint) <= WINDOW_S]
    if not near:
        return None
    return [round(statistics.median(p for p, _ in near), 1), round(statistics.median(r for _, r in near), 1)]


def trace(robot, why: str, before=None, volts: float | None = None, long_checkpoints: tuple | None = None) -> dict | None:
    """Record the tilt after the lie-down just commanded. `before` is the (pitch, roll) read just before it (or None), `volts` the pack reading taken before it. Returns the record, or None when off or
    when the robot cannot read the IMU."""
    path = log_path()
    if path is None or not callable(getattr(getattr(robot, "_lk", None), "poll_imu", None)):
        return None
    try:
        cps = long_checkpoints or checkpoints()
        frames = _frames(robot, max(cps) + WINDOW_S)
        peak = max((max(abs(p), abs(r)) for _, p, r in frames), default=None)
        fall_deg = math.degrees(getattr(robot, "_fall_rad", math.radians(60)))
        rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "why": why, "posture_before": getattr(robot, "posture", None),
               "before": None if before is None else [round(before[0], 1), round(before[1], 1)],
               "after": {f"{m:g}s": _at(frames, m) for m in cps}, "frames": len(frames),
               "peak_deg": None if peak is None else round(peak, 1), "flipped": bool(peak is not None and peak >= fall_deg),
               "pack_v": volts, "arm": list(getattr(robot, "_claw", ()) or ())}
        try:
            from ..telemetry.autolog import get_surface
            rec["floor"] = get_surface()
        except Exception:  # noqa: BLE001
            rec["floor"] = None
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        if rec["flipped"]:
            log.warning("lie-down (%s): the body went to %.0f deg", why, peak)
        else:
            log.info("lie-down (%s): %s", why, rec)
        return rec
    except Exception:  # noqa: BLE001
        log.debug("lie-down log failed", exc_info=True)
        return None


def pack_volts(robot) -> float | None:
    """The pack voltage read now (a `P` over the link), or None. Taken before the lie-down: the legs are still loaded then."""
    try:
        from ..power import battery
        return battery.read_voltage(robot._lk)
    except Exception:  # noqa: BLE001
        return None
