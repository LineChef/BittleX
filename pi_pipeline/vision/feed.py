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
    x: float
    y: float
    w: float
    h: float
    t: float = 0.0  # seconds, source clock

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
    """Parses detection messages from the camera module over serial.

    PROVISIONAL wire format (one JSON object per line) -- confirm against the
    real Grove Vision AI V2 / SenseCraft output when hardware is in hand:

        {"t": 12.34, "objs": [{"l": "person", "c": 0.82, "box": [x, y, w, h]}]}

    `pyserial` is imported lazily.
    """

    def __init__(self, port: str, baud: int = 921600):
        import serial

        self._ser = serial.Serial(port, baud, timeout=1)
        log.info("vision serial on %s @ %d", port, baud)

    def frames(self) -> Iterator[Frame]:
        while True:
            raw = self._ser.readline().decode("utf-8", "replace").strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.debug("unparseable vision line: %r", raw[:120])
                continue
            t = float(msg.get("t", 0.0))
            frame: Frame = []
            for o in msg.get("objs", []):
                try:
                    bx = o["box"]
                    frame.append(Detection(
                        str(o.get("l", "object")), float(o.get("c", 0.0)),
                        float(bx[0]), float(bx[1]), float(bx[2]), float(bx[3]), t,
                    ))
                except (KeyError, ValueError, TypeError):
                    continue
            yield frame

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass
