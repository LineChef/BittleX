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
    BatteryLevel.CRITICAL: "Pi battery is critically low.",
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

    def __init__(self, read_voltage, on_alert, *, monitor: BatteryMonitor | None = None, poll_s: float = 60.0,
                 record=None, record_every_s: float = 300.0, clock=time.monotonic):
        self._record, self._record_every_s, self._clock = record, record_every_s, clock
        self._last_recorded: float | None = None
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
        self._maybe_record(v)
        level = self.monitor.update(v, now)
        if level is not None:
            log.warning("battery %s: %.2f V", level.name.lower(), v)
            try:
                self._on_alert(level, v)
            except Exception:  # noqa: BLE001 -- an alert failing must not stop the watch
                log.debug("battery alert handler raised", exc_info=True)
        return level

    def _maybe_record(self, v: float) -> None:
        """Hand the reading to `record` at most once per `record_every_s` (the history of the discharge curve)."""
        if self._record is None:
            return
        t = self._clock()
        if self._last_recorded is not None and t - self._last_recorded < self._record_every_s:
            return
        self._last_recorded = t
        try:
            self._record(v)
        except Exception:  # noqa: BLE001 -- the history must never stop the watch
            log.debug("battery record raised", exc_info=True)

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


def make_voltage_log(path: str, max_bytes: int = 1_000_000):
    """A `record(volts)` callable that appends `local ISO time,volts` lines to `path` (created with a header; rotated to `path + ".1"` past
    `max_bytes`). Returns None for an empty path."""
    if not path:
        return None
    import os

    path = os.path.expanduser(path)

    def record(volts: float) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".1")
        new = not os.path.exists(path)
        with open(path, "a") as f:
            if new:
                f.write("time,volts\n")
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')},{volts:.2f}\n")

    return record


class LoadVoltageCheck:
    """Battery voltage taken WHILE G2 walks: asks (`P`) every `every_s`, picks the reply out of the link's non-IMU lines on later ticks and
    returns the alert level when one should fire. `send(cmd)` is fire-and-forget; `pop_other()` yields the non-IMU lines seen."""

    def __init__(self, send, pop_other, monitor: BatteryMonitor, *, every_s: float = 5.0, on_reading=None):
        self._send, self._pop, self.monitor, self._every = send, pop_other, monitor, every_s
        self._next = 0.0
        self._on_reading = on_reading

    def tick(self, now: float) -> tuple[BatteryLevel, float] | None:
        if now >= self._next:
            self._send("P")
            self._next = now + self._every
        result = None
        for line in self._pop() or []:
            v = parse_voltage(line) if str(line).startswith("Voltage") else None
            if v is None:
                continue
            if self._on_reading:
                self._on_reading(v)
            lvl = self.monitor.update(v, now)
            if lvl is not None and (result is None or lvl > result[0]):
                result = (lvl, v)
        return result
