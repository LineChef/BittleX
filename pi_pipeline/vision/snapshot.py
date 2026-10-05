"""Take one picture with G2's camera (the Grove Vision AI V2 on the Pi's USB), so Claude can describe what G2 sees.

The module only returns pictures when asked: `AT+INVOKE=1,0,0` runs one inference and replies with the detections AND a base64 JPEG
(`AT+INVOKE=-1,0,1`, used by the detection feed, returns detections only). `CameraSnapshotter` keeps the port open and the module idle,
and grabs a frame on demand. Only one process can own the camera port, so this is used by the voice service, not alongside the app's
vision feed. The picture is returned as-is: the module is mounted so its raw output is upright (docs/vision/detector-bench.md).

    python -m pi_pipeline.vision.snapshot --out /tmp/look.jpg"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger("g2.snapshot")

_BREAK = b"AT+BREAK\r\n"
_ONE_SHOT = b"AT+INVOKE=1,0,0\r\n"          # one inference, result WITH the jpeg
# OV5647 auto-exposure target registers (same as vision/feed.py): lifts a dim room
_AE_REGS = (("3A0F", 0x32), ("3A10", 0x24), ("3A1B", 0x32), ("3A1E", 0x24))


@dataclass
class Snapshot:
    jpeg: bytes
    width: int
    height: int
    detections: list = field(default_factory=list)      # (label, score 0..1, cx, cy, w, h) in frame fractions

    def hint(self, min_score: float = 0.4) -> str:
        """One line for Claude: what the on-device detector thought it saw (small, three-class model, so only a hint)."""
        seen = [d for d in self.detections if d[1] >= min_score]
        if not seen:
            return "On-device detector: nothing it knows (people or pets) in view."
        parts = []
        for label, score, cx, _cy, w, _h in seen:
            where = "left" if cx < 0.33 else "right" if cx > 0.67 else "center"
            size = "close" if w > 0.5 else "mid-distance" if w > 0.25 else "far"
            parts.append(f"{label} {score * 100:.0f}% ({where}, {size})")
        return "On-device detector (a small model, so only a hint): " + "; ".join(parts) + "."


def parse_invoke_line(line: str, labels: list[str] | None = None) -> Snapshot | None:
    """A module reply line -> Snapshot, or None if it is not a result carrying a picture."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None
    if msg.get("name") != "INVOKE" or msg.get("type") != 1:
        return None
    data = msg.get("data") or {}
    img = data.get("image")
    if not img:
        return None
    try:
        jpeg = base64.b64decode(img + "=" * (-len(img) % 4))
    except ValueError:
        return None
    res = data.get("resolution") or [240, 240]
    w, h = (res + res)[:2] if len(res) == 1 else res[:2]
    dets = []
    for b in data.get("boxes") or []:
        try:
            x, y, bw, bh, score, tid = b[:6]
            label = labels[int(tid)] if labels and 0 <= int(tid) < len(labels) else f"obj{int(tid)}"
            dets.append((label, float(score) / 100.0, x / w, y / h, bw / w, bh / h))
        except (ValueError, TypeError, ZeroDivisionError):
            continue
    return Snapshot(jpeg, int(w), int(h), dets)


# ---- exposure: the camera's auto-exposure target can be raised (dim rooms) or lowered (bright rooms, lamps) with `ae_bump`
BUMP_MIN, BUMP_MAX = -24, 64            # offsets from the module's stock target registers
CLIP_HIGH_PX, CLIP_LOW_PX = 245, 10      # luminance counted as blown out / crushed
TOO_BRIGHT_CLIP = 0.08                   # more than this share of blown-out pixels = too bright
TOO_DARK_MEAN, TOO_DARK_CLIP = 45.0, 0.45
TARGET_MEAN = 115.0


@dataclass
class ExposureStats:
    mean: float          # average luminance 0..255
    clip_high: float     # share of pixels at or above CLIP_HIGH_PX
    clip_low: float      # share of pixels at or below CLIP_LOW_PX


def exposure_stats(jpeg: bytes) -> ExposureStats | None:
    """Brightness statistics of a frame (needs Pillow; None if it cannot be read)."""
    try:
        import io

        from PIL import Image
        h = Image.open(io.BytesIO(jpeg)).convert("L").histogram()
        total = float(sum(h)) or 1.0
        return ExposureStats(sum(i * n for i, n in enumerate(h)) / total, sum(h[CLIP_HIGH_PX:]) / total, sum(h[:CLIP_LOW_PX + 1]) / total)
    except Exception:  # noqa: BLE001
        return None


def exposure_score(s: ExposureStats) -> float:
    """Lower is better: blown-out pixels cost the most (no detail is recoverable), then crushed ones, then distance from mid-grey."""
    return s.clip_high * 2.0 + s.clip_low * 1.0 + abs(s.mean - TARGET_MEAN) / 255.0


BRIGHTEN_TARGET = 100.0
LIFT_BELOW = 85.0                        # frames darker than this are lifted in software (a mean-54 dim-room frame shows far more detail
                                         # lifted to ~100; compared by eye 2026-10-05)


def brighten(jpeg: bytes, mean: float, target: float = BRIGHTEN_TARGET) -> bytes:
    """Lift the shadows of a dark frame in software (a gamma curve that moves its average luminance toward `target`). Measured on the real
    camera 2026-10-05: in a dim room the exposure-target registers change nothing (the sensor is already at its limit), so this is the only
    lever that works for a dark scene. Returns the input unchanged if it is not dark or cannot be processed."""
    try:
        import io
        import math

        from PIL import Image
        if mean >= target - 5 or mean <= 0:
            return jpeg
        gamma = max(0.4, min(1.0, math.log(target / 255.0) / math.log(max(mean, 1.0) / 255.0)))
        lut = [round(255 * (i / 255.0) ** gamma) for i in range(256)]
        im = Image.open(io.BytesIO(jpeg)).convert("RGB").point(lut * 3)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return jpeg


BRIGHT_CLIP_GOAL = 0.06                  # aim a bit under the "too bright" line so one move is enough
CLIP_PER_BUMP = 0.0032                   # measured 2026-10-05 with a desk lamp in view: each offset step changed the blown-out share by ~0.32%


def next_bump(bump: int, s: ExposureStats) -> int | None:
    """Where to move the exposure target for the next try given the last frame, or None if the frame is fine or there is no room left.
    For a bright frame the step is sized from how much of it is blown out (using the measured effect of one offset step), so a glaring
    lamp is fixed in one move and a mild case gets a gentle nudge; a dark frame gets a fixed step up."""
    if s.clip_high > TOO_BRIGHT_CLIP and s.clip_high >= s.clip_low:
        step = max(8, min(48, 4 * round((s.clip_high - BRIGHT_CLIP_GOAL) / CLIP_PER_BUMP / 4)))
        nb = max(BUMP_MIN, bump - step)
    elif s.mean < TOO_DARK_MEAN or s.clip_low > TOO_DARK_CLIP:
        nb = min(BUMP_MAX, bump + (32 if s.mean < 25 or s.clip_low > 0.8 else 16))
    else:
        return None
    return None if nb == bump else nb


class CameraSnapshotter:
    def __init__(self, port: str, baud: int = 921600, *, labels: list[str] | None = None, sensor_opt: int | None = None,
                 ae_bump: int = 0, timeout_s: float = 8.0, idle_close_s: float = 120.0, on_capture=None, save_dir: str | None = None, keep_days: float = 7.0, exposure_check: bool = True,
                 max_exposure_retries: int = 2, meter_every_s: float = 30.0, serial_factory=None,
                 sleep=time.sleep, clock=time.monotonic):
        self._port, self._baud, self._labels = port, baud, labels or []
        self._sensor_opt, self._ae_bump, self._timeout_s = sensor_opt, ae_bump, timeout_s
        self._factory, self._sleep, self._clock = serial_factory, sleep, clock
        self._ser = None
        self._lock = threading.Lock()
        self._idle_close_s = idle_close_s
        self._on_capture = on_capture                      # called once per picture taken (the shutter sound)
        self._keep_days = keep_days
        self._exposure_check, self._max_exposure_retries = exposure_check, max_exposure_retries
        self._meter_every_s = meter_every_s
        self._metered_at = float("-inf")                   # when the light was last measured (by a look or by the wake-word metering)
        self._dark_pinned = False                          # a step up changed nothing: the sensor is at its limit in this light
        self._settled: ExposureStats | None = None         # the exposure result the camera is currently set up for
        self._ae_default = ae_bump
        self._bump = ae_bump                               # the exposure offset in use now; adapts to the lighting and is remembered between looks
        self._save_dir = save_dir                          # opt-in: keep each picture here (for building a test set); normally None
        self._idle_timer: threading.Timer | None = None

    def _arm_idle_close(self) -> None:
        """Give the port back after a quiet spell, so tools like the camera preview can use it (the module is idle anyway)."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        if self._idle_close_s > 0:
            self._idle_timer = threading.Timer(self._idle_close_s, self.close)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _open(self) -> None:
        if self._ser is not None:
            return
        if self._factory is None:
            import serial
            self._factory = lambda: serial.Serial(self._port, self._baud, timeout=1)
        self._ser = self._factory()
        self._sleep(2.5)                                  # opening the port resets the module: let it boot
        self._ser.reset_input_buffer()
        self._ser.write(_BREAK); self._sleep(0.2)         # clear any inference loop left running
        if self._sensor_opt in (0, 1, 2):
            self._ser.write(f"AT+SENSOR=1,1,{self._sensor_opt}\r\n".encode()); self._sleep(0.8)
        if self._bump:
            self._apply_ae(self._bump)
        self._ser.reset_input_buffer()
        log.info("camera ready on %s (sensor_opt=%s, ae_bump=%s)", self._port, self._sensor_opt, self._bump)
        self._arm_idle_close()

    def _apply_ae(self, bump: int) -> None:
        """Move the auto-exposure target to the stock registers plus `bump` (clamped to values the sensor accepts)."""
        for addr, val in _AE_REGS:
            self._ser.write(f'AT+SETREG="0x{addr}","0x{max(0x08, min(0xF0, val + bump)):02X}"\r\n'.encode())
            self._sleep(0.25)

    def warm(self) -> None:
        """Open the camera now (a few seconds) and, if the light was not measured recently, meter it and set the exposure, so the first
        picture is already right and needs no retry. Runs while the person is still speaking. Never raises."""
        try:
            with self._lock:
                self._open()
                if self._exposure_check and self._clock() - self._metered_at > self._meter_every_s:
                    self._meter()
        except Exception:  # noqa: BLE001
            log.warning("camera could not be opened on %s", self._port, exc_info=True)
            self._ser = None

    def _save(self, snap: Snapshot) -> None:
        if not self._save_dir:
            return
        try:
            import os
            os.makedirs(self._save_dir, exist_ok=True)
            name = time.strftime("look_%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}.jpg"
            with open(os.path.join(self._save_dir, name), "wb") as f:
                f.write(snap.jpeg)
            log.info("saved picture to %s/%s", self._save_dir, name)
            from .pictures import prune_duplicates, prune_old
            prune_old(self._save_dir, self._keep_days)    # rule: pictures are deleted after a week
            prune_duplicates(self._save_dir)              # rule: near-duplicate pictures are pruned, earliest kept
        except Exception:  # noqa: BLE001
            log.debug("saving the picture failed", exc_info=True)

    def warm_async(self) -> None:
        """Start opening the camera in the background (the wake word was just heard, so a picture request may follow)."""
        threading.Thread(target=self.warm, name="camera-warm", daemon=True).start()

    def _meter(self) -> None:
        """Take a throwaway frame and settle the exposure on it (nothing is saved, sent or announced). Caller holds the lock."""
        frame, prev = None, None
        for _ in range(4):                                  # just after the camera opens, auto-exposure is still ramping: wait until it stops
            frame = self._grab_one()
            st = exposure_stats(frame.jpeg) if frame is not None else None
            if st is None:
                break
            if prev is not None and abs(st.mean - prev) < 6.0:
                break
            prev = st.mean
            self._sleep(0.4)
        if frame is not None:
            self._balance_exposure(frame, finish=False)
        self._metered_at = self._clock()

    def _grab_one(self) -> Snapshot | None:
        """One inference with its picture, or None if the module does not answer in time. Caller holds the lock."""
        self._ser.reset_input_buffer()
        self._ser.write(_ONE_SHOT)
        deadline = self._clock() + self._timeout_s
        while self._clock() < deadline:
            raw = self._ser.readline()
            if not raw:
                continue
            snap = parse_invoke_line(raw.decode("utf-8", "replace"), self._labels)
            if snap is not None:
                return snap
        log.warning("camera gave no picture within %.0f s", self._timeout_s)
        return None

    def _balance_exposure(self, first: Snapshot, finish: bool = True) -> Snapshot:
        """Check the frame's exposure and, if it is blown out or too dark, retry with the exposure target moved toward better light: a
        bright room lowers it, a dim room raises it, by an amount that grows with how bad the frame is. At most `max_exposure_retries`
        retries; the best-scoring frame wins, and its setting is kept for the next look in the same room."""
        stats = exposure_stats(first.jpeg)
        if stats is None:
            return first
        log.info("exposure: mean %.0f, blown-out %.0f%%, crushed %.0f%% (bump %d)", stats.mean, 100 * stats.clip_high,
                 100 * stats.clip_low, self._bump)
        if stats.mean >= LIFT_BELOW:
            self._dark_pinned = False                       # the room is brighter now: the target may work again, so try it when needed
        s0 = self._settled
        if s0 is not None and abs(stats.mean - s0.mean) < 12 and abs(stats.clip_high - s0.clip_high) < 0.04 \
                and abs(stats.clip_low - s0.clip_low) < 0.04:
            # the light is what the camera was already set up for (by the wake-word metering or the last look): no retries
            log.info("exposure unchanged since it was set; keeping the picture")
            return self._finish(first, stats) if finish else first
        best, best_stats, best_bump, cur = first, stats, self._bump, stats
        for attempt in range(1, self._max_exposure_retries + 1):
            nb = next_bump(self._bump, cur)
            if nb is None:
                break
            if nb > self._bump and self._dark_pinned:      # raising the target is known to do nothing in this light
                break
            prev_bump = self._bump
            self._apply_ae(nb)
            self._bump = nb
            self._sleep(0.5)
            if self._grab_one() is None:                    # let auto-exposure settle on the new target (this frame is thrown away)
                break
            frame = self._grab_one()
            st = exposure_stats(frame.jpeg) if frame else None
            if st is None:
                break
            log.info("exposure retry %d: bump %d -> mean %.0f, blown-out %.0f%%, crushed %.0f%%", attempt, nb, st.mean,
                     100 * st.clip_high, 100 * st.clip_low)
            if nb > prev_bump and abs(st.mean - cur.mean) < 2.0:
                self._dark_pinned = True                    # raised the target and the picture did not change
                log.info("exposure target has no effect in this light (sensor at its limit); will lift dark frames in software instead")
            better = exposure_score(st) < exposure_score(best_stats) - 0.02
            if exposure_score(st) < exposure_score(best_stats):
                best, best_stats, best_bump = frame, st, nb
            cur = st
            if not better:                                  # no real gain from this move: stop trying
                break
        if best_bump != self._bump:
            self._apply_ae(best_bump)                       # leave the camera at the best setting found
            self._bump = best_bump
        self._settled = best_stats                          # the camera is now set up for this light
        return self._finish(best, best_stats) if finish else best

    def _finish(self, snap: Snapshot, stats: ExposureStats) -> Snapshot:
        """The last touch on the picture that will be sent: a dim frame (below LIFT_BELOW) is lifted in software, because in a dim room the
        sensor is at its limit and no exposure setting can brighten it."""
        if stats.mean < LIFT_BELOW:
            lifted = brighten(snap.jpeg, stats.mean)
            if lifted is not snap.jpeg:
                new = exposure_stats(lifted)
                log.info("dark frame brightened in software: mean %.0f -> %.0f", stats.mean, new.mean if new else 0)
                return Snapshot(lifted, snap.width, snap.height, snap.detections)
        return snap

    def snapshot(self) -> Snapshot | None:
        """One picture (re-taken in better light if the first is badly exposed), or None if the camera is unavailable or does not answer
        in time. Never raises."""
        try:
            with self._lock:
                self._open()
                snap = self._grab_one()
                if snap is None:
                    return None
                if self._exposure_check:
                    snap = self._balance_exposure(snap)
                    self._metered_at = self._clock()
                log.info("camera snapshot: %dx%d, %d bytes, %d detections", snap.width, snap.height, len(snap.jpeg), len(snap.detections))
                self._arm_idle_close()
                self._save(snap)
                if self._on_capture:
                    try:
                        self._on_capture()
                    except Exception:  # noqa: BLE001
                        log.debug("on_capture handler raised", exc_info=True)
                return snap
        except Exception:  # noqa: BLE001
            log.warning("camera snapshot failed", exc_info=True)
            self._ser = None                               # reopen next time
        return None

    def close(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        with self._lock:
            if self._ser is not None:
                try:
                    self._ser.write(_BREAK)
                    self._ser.close()
                except Exception:  # noqa: BLE001
                    pass
                self._ser = None
            self._bump = self._ae_default                  # the module resets when the port reopens, and the light may have changed
            self._settled, self._metered_at = None, float("-inf")      # (the "target does nothing when it is dim" fact is kept: see below)


def main() -> None:
    import argparse
    import sys
    from pathlib import Path

    from ..config import settings

    ap = argparse.ArgumentParser(description="Take one picture with G2's camera and save it.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sensor-opt", type=int, default=None, help="0=240x240, 1=480x480, 2=640x480 (default: the VISION_SENSOR_OPT setting)")
    args = ap.parse_args()
    import logging
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    opt = settings.vision_sensor_opt if args.sensor_opt is None else args.sensor_opt
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=opt,
                            ae_bump=settings.vision_ae_bump)
    snap = cam.snapshot()
    cam.close()
    if snap is None:
        sys.exit("no picture")
    Path(args.out).write_bytes(snap.jpeg)
    print(f"saved {args.out}: {snap.width}x{snap.height}, {len(snap.jpeg)} bytes; {snap.hint()}")


if __name__ == "__main__":
    main()
