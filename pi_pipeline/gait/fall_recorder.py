"""The fall recorder: what the IMU saw before, during and after a fall, saved as one file per fall (2026-11-12).

The stand guard already reads every IMU frame. This keeps the last `PRE_S` seconds, and when the guard calls a fall it keeps collecting for `POST_S` more seconds (the tip, the settle, the position he
ends up resting in), then writes `~/.local/share/g2/falls/<date>_<time>.json` (`G2_FALL_DIR` moves it, `G2_FALL_RECORD=off` turns it off). Each file holds:
  - the trace: seconds from the fall call, roll, pitch, yaw (degrees), the three gyro rates (degrees per second), the three accelerations as printed;
  - the summary: the peak tilt, when the tilt first passed 20 and 45 degrees, how long the tip took from 20 to 60 degrees, the direction it went (roll and pitch at the peak), the rest position (median of the
    last frames) and the gravity direction there (which side of the body is on the floor);
  - the context: the last motion command, and the commands the Pi sent in the 40 s before (from the command log).
Never raises: a recorder error is logged and the fall handling goes on.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from collections import deque
from pathlib import Path

log = logging.getLogger("g2.fall_recorder")

PRE_S = 20.0           # seconds of frames kept before the fall call
POST_S = 8.0           # seconds collected after it
CMD_WINDOW_S = 40.0    # the Pi's commands this far back are copied in


def enabled() -> bool:
    return os.environ.get("G2_FALL_RECORD", "").strip().lower() not in ("0", "off", "false", "no")


def folder() -> Path:
    v = os.environ.get("G2_FALL_DIR", "").strip()
    return Path(v) if v else Path.home() / ".local" / "share" / "g2" / "falls"


def _recent_commands(window_s: float, wall: float) -> list[dict]:
    """The Pi's commands in the last `window_s` seconds from the command log (its tail only: the file can be large)."""
    try:
        from ..link import command_log
        p = command_log.path()
        if p is None or not p.exists():
            return []
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 400_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(wall - window_s))
        out = []
        for ln in lines[1:] if size > 400_000 else lines:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("dir") == "pi" and r.get("t", "") >= cutoff:
                out.append({"t": r.get("t"), "cmd": r.get("cmd"), "source": r.get("source")})
        return out[-120:]
    except Exception:  # noqa: BLE001
        return []


def _median(v: list[float]) -> float:
    s = sorted(v)
    return s[len(s) // 2] if s else 0.0


def summarize(rows: list[list[float]]) -> dict:
    """The numbers worth reading first, from trace rows [t, roll, pitch, yaw, gx, gy, gz, ax, ay, az]."""
    out: dict = {"frames": len(rows)}
    if not rows:
        return out
    tilt = [max(abs(r[1]), abs(r[2])) for r in rows]
    peak_i = max(range(len(rows)), key=lambda i: tilt[i])
    out["peak_tilt_deg"] = round(tilt[peak_i], 1)
    out["roll_at_peak_deg"], out["pitch_at_peak_deg"] = round(rows[peak_i][1], 1), round(rows[peak_i][2], 1)
    for name, lim in (("first_over_20_s", 20.0), ("first_over_45_s", 45.0), ("first_over_60_s", 60.0)):
        hit = next((r[0] for r, t in zip(rows, tilt) if t > lim), None)
        out[name] = None if hit is None else round(hit, 2)
    a, b = out["first_over_20_s"], out["first_over_60_s"]
    out["tip_from_20_to_60_s"] = None if a is None or b is None else round(b - a, 2)
    tail = rows[-10:]
    out["rest_roll_deg"], out["rest_pitch_deg"] = round(_median([r[1] for r in tail]), 1), round(_median([r[2] for r in tail]), 1)
    out["rest_accel"] = [round(_median([r[k] for r in tail]), 2) for k in (7, 8, 9)]          # gravity in the body frame: the axis near +-10 is the side facing the floor
    ax, ay, az = out["rest_accel"]
    mag = max(abs(ax), abs(ay), abs(az)) or 1.0
    axis = max(("x", abs(ax)), ("y", abs(ay)), ("z", abs(az)), key=lambda p: p[1])[0]
    out["floor_side_axis"] = f"{'+' if {'x': ax, 'y': ay, 'z': az}[axis] > 0 else '-'}{axis}" if mag > 3.0 else "unknown"
    return out


class FallRecorder:
    def __init__(self, link=None, *, clock=time.monotonic, wall=time.time, directory: Path | None = None, pre_s: float = PRE_S, post_s: float = POST_S):
        self._link, self._clock, self._wall = link, clock, wall
        self._dir, self._pre_s, self._post_s = directory, pre_s, post_s
        self._buf: deque = deque()                 # (t, roll, pitch, yaw, gx, gy, gz, ax, ay, az), degrees
        self._pending: dict | None = None
        self.saved: list[Path] = []

    def feed(self, now: float, line: str) -> None:
        """One IMU line from the stream (anything that is not an IMU frame is ignored)."""
        try:
            from .imu_parse import parse_imu_accel, parse_imu_line
            r = parse_imu_line(line)
            if r is None:
                return
            a = parse_imu_accel(line) or (0.0, 0.0, 0.0)
            row = (now, math.degrees(r[0]), math.degrees(r[1]), math.degrees(r[2]), math.degrees(r[3]), math.degrees(r[4]), math.degrees(r[5]), a[0], a[1], a[2])
            self._buf.append(row)
            while self._buf and now - self._buf[0][0] > self._pre_s + (self._post_s if self._pending else 0.0) + 5.0:
                self._buf.popleft()
            if self._pending is not None and now >= self._pending["until"]:
                self.flush()
        except Exception:  # noqa: BLE001
            log.debug("fall recorder feed failed", exc_info=True)

    def trigger(self, now: float, tilt_deg: float, **context) -> None:
        """The guard called a fall. Collection continues for `post_s`; a second call during that time is ignored."""
        if self._pending is not None:
            return
        try:
            ctx = dict(context)
            ctx["tilt_deg"] = round(float(tilt_deg), 1)
            ctx["last_motion_command"] = (getattr(self._link, "last_motion_command", "") or "") if self._link is not None else ""
            self._pending = {"t0": now, "until": now + self._post_s, "wall": self._wall(), "context": ctx}
        except Exception:  # noqa: BLE001
            log.debug("fall recorder trigger failed", exc_info=True)

    def flush(self) -> Path | None:
        """Write the pending fall (early, if the guard is stopping). Returns the file, or None."""
        p, self._pending = self._pending, None
        if p is None:
            return None
        try:
            t0 = p["t0"]
            rows = [[round(r[0] - t0, 2)] + [round(v, 2) for v in r[1:]] for r in self._buf if r[0] >= t0 - self._pre_s]
            d = self._dir or folder()
            d.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(p["wall"]))
            doc = {"when": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p["wall"])), "columns": ["t_s", "roll", "pitch", "yaw", "gx", "gy", "gz", "ax", "ay", "az"],
                   "context": p["context"], "summary": summarize(rows), "commands": _recent_commands(CMD_WINDOW_S + self._post_s, self._wall()), "trace": rows}
            path = d / f"{stamp}.json"
            path.write_text(json.dumps(doc) + "\n")
            self.saved.append(path)
            log.warning("fall recorded: %s (peak tilt %s deg, resting on %s)", path, doc["summary"].get("peak_tilt_deg"), doc["summary"].get("floor_side_axis"))
            return path
        except Exception:  # noqa: BLE001
            log.exception("could not save the fall record")
            return None
