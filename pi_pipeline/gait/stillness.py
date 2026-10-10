"""Wait until G2 has stopped swaying before a picture is taken (user, 2026-10-10: "wait for the IMU to show G2 has stopped swaying before taking each picture, that will limit camera shake").

`StillnessWaiter` reads the 5 Hz IMU print (roll and pitch) from a fan-out consumer of the serial link and says "still" once the newest `window` frames (1 s) all agree within `max_std_deg`
(standing steady noise is about 0.1 degrees; a sway or a wobble is 1 to 6 degrees). It waits for NEW frames, so a body that was swaying a moment ago does not count. If no frames come at all
(the IMU print is off, the board is not connected) it gives up after `timeout_s` and the picture is taken anyway: a missing IMU must never stop a picture."""
from __future__ import annotations

import logging
import math
import time
from collections import deque

from .imu_parse import parse_imu_line

log = logging.getLogger("g2.stillness")


class StillnessWaiter:
    def __init__(self, poll, *, window: int = 5, max_std_deg: float = 0.5, clock=time.monotonic, sleep=time.sleep, poll_s: float = 0.1):
        self._poll = poll                                    # poll() -> a list of raw IMU lines (SerialLink.poll_imu / an ImuFanout consumer's poll_imu)
        self.window, self.max_std_deg = window, max_std_deg
        self._clock, self._sleep, self._poll_s = clock, sleep, poll_s
        self.last_std: float | None = None

    @staticmethod
    def _std(vals) -> float:
        m = sum(vals) / len(vals)
        return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))

    def wait(self, timeout_s: float = 6.0) -> bool | None:
        """True once the body is still; False if it was still swaying at the timeout; None if no IMU frames arrived at all."""
        t0 = self._clock()
        frames: deque = deque(maxlen=self.window)
        try:
            self._poll()                                     # drain old frames: only NEW ones count
        except Exception:  # noqa: BLE001
            return None
        got = 0
        while self._clock() - t0 < timeout_s:
            try:
                lines = self._poll() or []
            except Exception:  # noqa: BLE001
                return None
            for line in lines:
                r = parse_imu_line(line)
                if r is not None:
                    frames.append((math.degrees(r[0]), math.degrees(r[1])))
                    got += 1
            if len(frames) >= self.window:
                s = max(self._std([f[0] for f in frames]), self._std([f[1] for f in frames]))
                self.last_std = s
                if s <= self.max_std_deg:
                    return True
            self._sleep(self._poll_s)
        if got == 0:
            log.info("no IMU frames while waiting for G2 to be still: taking the picture anyway")
            return None
        log.info("G2 was still swaying (std %.2f deg) after %.1f s: taking the picture anyway", self.last_std or 0.0, timeout_s)
        return False
