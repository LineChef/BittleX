"""Detections coming off the AI Vision Camera Module.

The camera module runs object detection on-device and sends results to the Pi
over serial (it can't stream frames -- see docs/project-plan.md Phase 8). This
module turns that stream into `Detection` objects, behind a `DetectionFeed`
interface with a mock implementation so the avoidance logic and the
scene-description path are testable now.

`Detection` boxes are normalised to [0, 1]: (x, y) top-left, (w, h) size.
Derived: `area` (a closeness proxy -- bigger box = nearer), `center_x` (bearing).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Iterable, Iterator, Protocol

log = logging.getLogger("g2.vision.feed")


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    x: float          # top-left, normalised [0, 1]
    y: float
    w: float
    h: float
    t: float = 0.0    # seconds, source clock

    @classmethod
    def from_center_px(cls, label, confidence, cx, cy, w, h, frame_px, t=0.0):
        """The camera reports box centre in model-input pixels; store top-left
        normalised to [0, 1]."""
        f = float(frame_px)
        return cls(label, confidence, (cx - w / 2) / f, (cy - h / 2) / f, w / f, h / f, t)

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    @property
    def center_x(self) -> float:
        return self.x + self.w / 2

    @property
    def bearing(self) -> str:
        c = self.center_x
        return "left" if c < 0.40 else "right" if c > 0.60 else "ahead"


Frame = list[Detection]  # all detections reported at one instant


class DetectionFeed(Protocol):
    def frames(self) -> Iterator[Frame]:
        """Yield frames until the source ends (mock) or forever (serial)."""
        ...

    def close(self) -> None: ...


class MockDetectionFeed:
    """Replays a scripted list of frames. `interval` sleeps between frames so a
    consumer sees them at a realistic rate; set 0 in tests."""

    def __init__(self, script: Iterable[Frame], interval: float = 0.0):
        self._script = list(script)
        self._interval = interval

    def frames(self) -> Iterator[Frame]:
        for fr in self._script:
            yield fr
            if self._interval:
                time.sleep(self._interval)

    def close(self) -> None:
        pass

    # --- helpers to build scripts ---
    @staticmethod
    def approaching(label: str = "box", steps: int = 8, bearing: float = 0.5) -> list[Frame]:
        """One object growing from far to near, centred at `bearing` (0..1)."""
        out: list[Frame] = []
        for i in range(steps):
            s = 0.06 + (0.66 - 0.06) * i / max(1, steps - 1)  # box side 6% -> 66% (area .004 -> .44)
            out.append([Detection(label, 0.85, bearing - s / 2, 0.5 - s / 2, s, s, float(i))])
        return out


class SerialDetectionFeed:
    """Parses object-detection events from the Grove Vision AI V2 (SenseCraft /
    SSCMA firmware) over a serial link -- USB-C to the Pi's USB data port
    (`/dev/ttyACM0`), which is how SenseCraft talks to it too. (The Grove 4-pin
    connector is I2C, addr 0x62, not a UART.)

    The module does NOT stream on its own -- a client has to start inference.
    On open we send ``AT+INVOKE=-1,0,1`` (loop forever, results only, no JPEG);
    on close, ``AT+BREAK``. Verified against real hardware 2026-09-05.

    Message format (one JSON object per line, 921600 baud):

        {"type":1,"name":"INVOKE","code":0,
         "data":{"count":8,"perf":[7,50,0],"resolution":[240,240],
                 "boxes":[[x, y, w, h, score, target_id], ...]}}

    `boxes` values are integers: box **centre** (x, y) and size (w, h) in
    model-input pixels (confirmed centre, not top-left, on hardware), `score`
    0-100, `target_id` a class index. Only `type == 1` messages carry results
    (`type == 0` is the command ack). Labels aren't in the message -- they come
    from `labels` (the deployed model's class list, in id order). `perf` lines,
    the boot banner, and other events are ignored.

    `frame_px` is the model input size used to normalise coordinates; the
    `resolution` field in each message reports it (240 for the common
    pretrained models). `pyserial` is imported lazily.
    """

    _START_CMD = b"AT+INVOKE=-1,0,1\r\n"
    _STOP_CMD = b"AT+BREAK\r\n"
    # OV5647 auto-exposure target regs (WPT/BPT enter + go-out). Stock Himax
    # tuning aims dim (~0x32/0x24); adding `ae_bump` lifts the whole image so
    # faces/obstacles are visible in a low-light room. Runtime-only -- must be
    # re-applied every power-up (this class does, on open).
    _AE_REGS = (("3A0F", 0x32), ("3A10", 0x24), ("3A1B", 0x32), ("3A1E", 0x24))

    def __init__(
        self,
        port: str,
        baud: int = 921600,
        *,
        frame_px: int = 240,
        labels: list[str] | None = None,
        min_score: int = 0,
        auto_start: bool = True,
        sensor_opt: int | None = None,   # 0=240 1=480 2=640x480; None = leave as-is
        ae_bump: int = 0,               # 0 = off; ~0x20 helps a dim room, over-exposes a bright one
    ):
        import serial

        self._ser = serial.Serial(port, baud, timeout=1)
        self._frame_px = frame_px
        self._labels = labels or []
        self._min_score = min_score
        self._t = 0.0
        if auto_start:
            time.sleep(2.5)              # let the module boot (port open resets it)
            self._ser.reset_input_buffer()
            self._ser.write(self._STOP_CMD)     # clear any prior INVOKE loop
            time.sleep(0.2)
            self._apply_sensor(sensor_opt, ae_bump)
            self._ser.reset_input_buffer()
            self._ser.write(self._START_CMD)
        log.info("vision serial on %s @ %d (frame %dpx, sensor_opt=%s, ae_bump=%s)",
                 port, baud, frame_px, sensor_opt, ae_bump)

    def _apply_sensor(self, sensor_opt: int | None, ae_bump: int) -> None:
        if sensor_opt in (0, 1, 2):
            self._ser.write(f"AT+SENSOR=1,1,{sensor_opt}\r\n".encode())
            time.sleep(0.8)
        if ae_bump:
            for a, v in self._AE_REGS:
                self._ser.write(
                    f'AT+SETREG="0x{a}","0x{min(0xF0, v + ae_bump):02X}"\r\n'.encode())
                time.sleep(0.25)

    def _label(self, target_id: int) -> str:
        if 0 <= target_id < len(self._labels):
            return self._labels[target_id]
        return f"obj{target_id}"

    def frames(self) -> Iterator[Frame]:
        while True:
            raw = self._ser.readline().decode("utf-8", "replace").strip()
            if not raw or not raw.startswith("{"):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.debug("unparseable vision line: %r", raw[:120])
                continue
            if msg.get("name") != "INVOKE" or msg.get("type") != 1:
                continue
            self._t += 1.0
            data = msg.get("data", {})
            # boxes are in the frame the message reports (240 or 480 depending
            # on the sensor option) -- trust it over the constructor default
            res = data.get("resolution") or [self._frame_px]
            frame_px = res[0] or self._frame_px
            frame: Frame = []
            for b in data.get("boxes", []):
                try:
                    x, y, w, h, score, tid = b[:6]
                    if score < self._min_score:
                        continue
                    frame.append(Detection.from_center_px(
                        self._label(int(tid)), float(score) / 100.0,
                        float(x), float(y), float(w), float(h), frame_px, self._t,
                    ))
                except (ValueError, TypeError):
                    continue
            yield frame

    def close(self) -> None:
        try:
            self._ser.write(self._STOP_CMD)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass
