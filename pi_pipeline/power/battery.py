"""G2's low-battery watch: read the robot's 2-cell pack voltage with the firmware's `P` command, decide when it is low, alert.

The pack is 7.4 V nominal (2S Li-ion): ~8.4 V full, ~7.9 V about 60%, ~7.0 V low, ~6.6 V critical (it already sags to ~6.6 V under
load), ~6.0 V empty. Readings under load sag, so an alert needs `confirm` consecutive low readings and the watcher doesn't read
while a gait is running. The Pi's own PiSugar battery has no telemetry and can't be watched this way.

`parse_voltage` / `BatteryMonitor` are pure logic; `BatteryWatcher` polls a `read_voltage()` callable on a background thread."""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from enum import IntEnum

log = logging.getLogger("g2.battery")

_VOLTAGE = re.compile(r"Voltage:\s*([0-9]+(?:\.[0-9]+)?)\s*V")


def parse_voltage(text: str | None) -> float | None:
    """'Voltage: 7.89 V' -> 7.89. The reply can arrive mixed with echoed characters; None if there is no reading."""
    m = _VOLTAGE.search(text or "")
    return float(m.group(1)) if m else None


def read_voltage(link, *, attempts: int = 3, drain_s: float = 0.2) -> float | None:
    """Ask the BiBoard for its battery voltage over `link` (a SerialLink). Drains stray lines first and retries, as the
    firmware sometimes interleaves other output. None if no valid reading after `attempts`."""
    from ..link import opencat

    for _ in range(attempts):
        try:
            link.drain(drain_s)
            v = parse_voltage(link.send(opencat.PRINT_VOLTAGE))
        except Exception:  # noqa: BLE001 -- a failed read must never take the watcher down
            log.debug("voltage read failed", exc_info=True)
            continue
        if v is not None:
            return v
    return None


class BatteryLevel(IntEnum):
    OK = 0
    LOW = 1
    CRITICAL = 2


# What G2 says after the siren (spoken in its robot voice by the voice service)
ALERT_MESSAGES = {
    BatteryLevel.LOW: "My battery is low.",
    BatteryLevel.CRITICAL: "My battery is critically low. Please charge me.",
}


PI_ALERT_MESSAGES = {
    BatteryLevel.LOW: "Pi battery is low.",
    BatteryLevel.CRITICAL: "My Pi battery is almost empty. Please charge me.",
}


class BatteryMonitor:
    """Feed it voltage readings; it returns a `BatteryLevel` when an alert should fire, else None.

    A level only counts once the last `confirm` readings are all at or below its threshold. Getting worse alerts at once;
    staying at LOW/CRITICAL alerts again every `repeat_s`; it resets to OK once readings recover above `low_v + hysteresis_v`."""

    def __init__(self, low_v: float = 7.0, critical_v: float = 6.6, confirm: int = 3,
                 hysteresis_v: float = 0.15, repeat_s: float = 300.0):
        self.low_v, self.critical_v = low_v, critical_v
        self.hysteresis_v, self.repeat_s = hysteresis_v, repeat_s
        self._recent: deque[float] = deque(maxlen=max(1, confirm))
        self.level = BatteryLevel.OK
        self._last_alert: float | None = None

    def update(self, volts: float, now: float | None = None) -> BatteryLevel | None:
        now = time.monotonic() if now is None else now
        self._recent.append(volts)
        if len(self._recent) < self._recent.maxlen:
            return None
        worst = max(self._recent)          # the least-low of the confirmed readings
        if worst <= self.critical_v:
            seen = BatteryLevel.CRITICAL
        elif worst <= self.low_v:
            seen = BatteryLevel.LOW
        elif worst >= self.low_v + self.hysteresis_v:
            seen = BatteryLevel.OK
        else:
            seen = self.level              # in the hysteresis band: hold the current level
        if seen == BatteryLevel.OK:
            self.level, self._last_alert = BatteryLevel.OK, None
            return None
        worse = seen > self.level
        self.level = seen
        if worse or self._last_alert is None or now - self._last_alert >= self.repeat_s:
            self._last_alert = now
            return seen
        return None


class BatteryWatcher:
    """Polls `read_voltage()` every `poll_s` on a daemon thread and calls `on_alert(level, volts)` when the monitor says to.
    `read_voltage` returns volts or None (e.g. a gait is running, or no link): None readings are skipped."""

    def __init__(self, read_voltage, on_alert, *, monitor: BatteryMonitor | None = None, poll_s: float = 60.0):
        self._read = read_voltage
        self._on_alert = on_alert
        self.monitor = monitor or BatteryMonitor()
        self._poll_s = poll_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_volts: float | None = None

    def poll_once(self, now: float | None = None) -> BatteryLevel | None:
        try:
            v = self._read()
        except Exception:  # noqa: BLE001
            log.debug("battery read raised", exc_info=True)
            return None
        if v is None:
            return None
        self.last_volts = v
        level = self.monitor.update(v, now)
        if level is not None:
            log.warning("battery %s: %.2f V", level.name.lower(), v)
            try:
                self._on_alert(level, v)
            except Exception:  # noqa: BLE001 -- an alert failing must not stop the watch
                log.debug("battery alert handler raised", exc_info=True)
        return level

    def start(self) -> "BatteryWatcher":
        def _run() -> None:
            while True:
                self.poll_once()
                if self._stop.wait(self._poll_s):
                    return
        self._thread = threading.Thread(target=_run, name="battery-watch", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
