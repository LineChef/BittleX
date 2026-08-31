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
    SSCMA firmware) over UART.

    Message format (one JSON object per line, default 921600 baud):

        {"type":1,"name":"INVOKE","code":0,
         "data":{"count":8,"perf":[8,365,0],
                 "boxes":[[x, y, w, h, score, target_id], ...]}}

    `boxes` values are integers: box centre (x, y) and size (w, h) in
    model-input pixels, `score` 0-100, `target_id` a class index. Labels aren't
    in the message -- they come from `labels` (the deployed model's class list,
    in id order). `perf` lines and other events are ignored.

    `frame_px` is the model input size used to normalise coordinates (192 or 240
    for the common pretrained models). `pyserial` is imported lazily.
    """

    def __init__(
        self,
        port: str,
        baud: int = 921600,
        *,
        frame_px: int = 240,
        labels: list[str] | None = None,
        min_score: int = 0,
    ):
        import serial

        self._ser = serial.Serial(port, baud, timeout=1)
        self._frame_px = frame_px
        self._labels = labels or []
        self._min_score = min_score
        self._t = 0.0
        log.info("vision serial on %s @ %d (frame %dpx)", port, baud, frame_px)

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
            if msg.get("name") != "INVOKE":
                continue
            self._t += 1.0
            frame: Frame = []
            for b in msg.get("data", {}).get("boxes", []):
                try:
                    x, y, w, h, score, tid = b[:6]
                    if score < self._min_score:
                        continue
                    frame.append(Detection.from_center_px(
                        self._label(int(tid)), float(score) / 100.0,
                        float(x), float(y), float(w), float(h), self._frame_px, self._t,
                    ))
                except (ValueError, TypeError):
                    continue
            yield frame

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass
