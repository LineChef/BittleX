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
import threading
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
        detection_filter=None,          # frame -> frame, applied to every frame the feed yields (vision/detection_filter.py)
        snapshot_sensor_opt: int | None = 0,   # pictures are taken at this capture option (0 = 240 x 240), then detection goes back to `sensor_opt`; None = no switch
    ):
        import serial

        self._ser = serial.Serial(port, baud, timeout=1)
        self._io_lock = threading.Lock()         # one reader or one snapshot on the port at a time
        self._paused = threading.Event()         # set while snapshot() has the port: frames() waits
        self._frame_px = frame_px
        self._labels = labels or []
        self._min_score = min_score
        self._sensor_opt, self._ae_bump, self._snap_opt = sensor_opt, ae_bump, snapshot_sensor_opt
        self._filter = detection_filter
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
        # reads and parses one detection message per loop, skipping anything
        # that isn't a results-carrying INVOKE line
        while True:
            if self._paused.is_set():            # a picture is being taken on this port
                time.sleep(0.05)
                continue
            with self._io_lock:
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
            if self._filter is not None:
                frame = self._filter(frame)
            yield frame

    def snapshot(self, timeout_s: float = 6.0):
        """Take ONE picture on this feed's own port and go back to detecting: stops the detection loop, asks for a single inference that
        comes back with its JPEG (`AT+INVOKE=1,0,0`), then restarts the loop. Returns a `vision.snapshot.Snapshot`, or None if the module
        did not answer in time. The detection stream is dark for about a second. The pause is in the reader (`frames()`), so this is safe
        to call from another thread while a `BackgroundFrameSource` is reading. No network, no API call."""
        from .snapshot import parse_invoke_line
        switched = False
        self._paused.set()
        snap = None
        try:
            with self._io_lock:                  # waits for a readline() in progress (at most its 1 s timeout)
                self._ser.write(self._STOP_CMD)
                time.sleep(0.2)
                switched = self._sensor_opt is not None and self._snap_opt is not None and self._snap_opt != self._sensor_opt
                if switched:
                    # the module's picture buffer holds only about 5 KB of JPEG: a 480 x 480 capture comes back cut off (only the top third to half is real, the rest gray),
                    # a 240 x 240 one fits. So pictures are taken at 240 and detection goes back to its own capture option afterwards.
                    self._apply_sensor(self._snap_opt, self._ae_bump)
                self._ser.reset_input_buffer()
                self._ser.write(b"AT+INVOKE=1,0,0\r\n")
                deadline = time.monotonic() + timeout_s
                while time.monotonic() < deadline:
                    raw = self._ser.readline()
                    if not raw:
                        continue
                    snap = parse_invoke_line(raw.decode("utf-8", "replace"), self._labels)
                    if snap is not None:
                        break
                if snap is None:
                    log.warning("camera gave no picture within %.0f s", timeout_s)
                self._ser.write(self._STOP_CMD)
                time.sleep(0.2)
                if switched:
                    self._apply_sensor(self._sensor_opt, self._ae_bump)
                self._ser.reset_input_buffer()
                self._ser.write(self._START_CMD)     # back to detections
        finally:
            self._paused.clear()
        if snap is not None:
            from ..voice import shutter
            shutter.click()                      # every picture taken makes the double click
        return snap

    def close(self) -> None:
        try:
            self._ser.write(self._STOP_CMD)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass


class BackgroundFrameSource:
    """Non-blocking "latest frame" view of a `DetectionFeed`.

    `SerialDetectionFeed.frames()` blocks in `readline()` (up to 1 s per call),
    which would stall a fixed-rate behaviour loop that asks for a frame every
    tick. This reads the feed on a daemon thread and keeps only the newest
    frame; calling the instance returns it instantly.

    A frame older than `max_age_s` is reported as `[]` ("nothing seen"), so a
    dead or unplugged camera degrades to no detections rather than a frozen
    last-seen scene. `failed` is set if the reader thread dies.
    """

    def __init__(self, feed, *, max_age_s: float = 1.0, clock=time.monotonic):
        self._feed = feed
        self._max_age_s = max_age_s
        self._clock = clock
        self._lock = threading.Lock()
        self._frame: Frame = []
        self._at: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.failed: str | None = None

    def start(self) -> "BackgroundFrameSource":
        self._thread = threading.Thread(target=self._run, name="vision-feed", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            for frame in self._feed.frames():
                if self._stop.is_set():
                    return
                with self._lock:
                    self._frame, self._at = frame, self._clock()
        except Exception as e:  # noqa: BLE001 -- a reader death must not kill the app
            if not self._stop.is_set():
                self.failed = repr(e)
                log.error("vision feed reader died: %r", e)

    def __call__(self) -> Frame:
        with self._lock:
            if self._at is None or self._clock() - self._at > self._max_age_s:
                return []
            return list(self._frame)

    def snapshot(self, timeout_s: float = 6.0):
        """One picture from the underlying feed (see `SerialDetectionFeed.snapshot`), or None if the feed cannot take pictures. The newest
        detection frame is cleared so a stale one is not read as current right after the pause."""
        fn = getattr(self._feed, "snapshot", None)
        if fn is None:
            return None
        snap = fn(timeout_s)
        with self._lock:
            self._at = None
        return snap

    def close(self) -> None:
        self._stop.set()
        self._feed.close()
