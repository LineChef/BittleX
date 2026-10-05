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


class CameraSnapshotter:
    def __init__(self, port: str, baud: int = 921600, *, labels: list[str] | None = None, sensor_opt: int | None = None,
                 ae_bump: int = 0, timeout_s: float = 8.0, idle_close_s: float = 120.0, on_capture=None, save_dir: str | None = None, serial_factory=None,
                 sleep=time.sleep, clock=time.monotonic):
        self._port, self._baud, self._labels = port, baud, labels or []
        self._sensor_opt, self._ae_bump, self._timeout_s = sensor_opt, ae_bump, timeout_s
        self._factory, self._sleep, self._clock = serial_factory, sleep, clock
        self._ser = None
        self._lock = threading.Lock()
        self._idle_close_s = idle_close_s
        self._on_capture = on_capture                      # called once per picture taken (the shutter sound)
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
        if self._ae_bump:
            for addr, val in _AE_REGS:
                self._ser.write(f'AT+SETREG="0x{addr}","0x{min(0xF0, val + self._ae_bump):02X}"\r\n'.encode()); self._sleep(0.25)
        self._ser.reset_input_buffer()
        log.info("camera ready on %s (sensor_opt=%s, ae_bump=%s)", self._port, self._sensor_opt, self._ae_bump)
        self._arm_idle_close()

    def warm(self) -> None:
        """Open the camera now (a few seconds) so the first snapshot is quick. Never raises."""
        try:
            with self._lock:
                self._open()
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
            from .pictures import prune_duplicates
            prune_duplicates(self._save_dir)              # rule: near-duplicate pictures are pruned, earliest kept
        except Exception:  # noqa: BLE001
            log.debug("saving the picture failed", exc_info=True)

    def warm_async(self) -> None:
        """Start opening the camera in the background (the wake word was just heard, so a picture request may follow)."""
        threading.Thread(target=self.warm, name="camera-warm", daemon=True).start()

    def snapshot(self) -> Snapshot | None:
        """One picture, or None if the camera is unavailable or does not answer in time. Never raises."""
        try:
            with self._lock:
                self._open()
                self._ser.reset_input_buffer()
                self._ser.write(_ONE_SHOT)
                deadline = self._clock() + self._timeout_s
                while self._clock() < deadline:
                    raw = self._ser.readline()
                    if not raw:
                        continue
                    snap = parse_invoke_line(raw.decode("utf-8", "replace"), self._labels)
                    if snap is not None:
                        log.info("camera snapshot: %dx%d, %d bytes, %d detections", snap.width, snap.height, len(snap.jpeg),
                                 len(snap.detections))
                        self._arm_idle_close()
                        self._save(snap)
                        if self._on_capture:
                            try:
                                self._on_capture()
                            except Exception:  # noqa: BLE001
                                log.debug("on_capture handler raised", exc_info=True)
                        return snap
                log.warning("camera gave no picture within %.0f s", self._timeout_s)
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


def main() -> None:
    import argparse
    import sys
    from pathlib import Path

    from ..config import settings

    ap = argparse.ArgumentParser(description="Take one picture with G2's camera and save it.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sensor-opt", type=int, default=None, help="0=240x240, 1=480x480, 2=640x480 (default: the VISION_SENSOR_OPT setting)")
    args = ap.parse_args()
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
