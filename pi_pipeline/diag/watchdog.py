"""Watchdog + heartbeat for the control loop (diagnostics Phase 2).

The control loop (`gait/run_gait.py`, later the behaviour driver) calls
`wd.beat()` once per tick. A background thread:

  * logs `sys/INFO/heartbeat` every `heartbeat_every_s` with the measured loop Hz
  * if no beat for `stall_after_s` (hung ONNX, serial stall, Pi throttle) →
    logs `sys/ERROR/loop.stall` (which auto-flushes the black box) and calls
    `on_stall()` -- the caller wires that to a safe stop (send `d`)
  * optionally polls a `Sysmon` each heartbeat for battery / Pi-thermal events

The stall decision is a pure function (`WatchdogCore.poll`) so it's unit-tested
with a fake clock; the thread is a thin timer around it.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum

from . import core


class WatchVerdict(Enum):
    OK = "ok"
    HEARTBEAT = "heartbeat"   # time to log a periodic heartbeat
    STALL = "stall"           # loop has gone silent past the threshold


@dataclass
class WatchdogConfig:
    stall_after_s: float = 0.25       # no beat for this long -> STALL
    heartbeat_every_s: float = 1.0    # periodic heartbeat log interval
    startup_grace_s: float = 2.0      # ignore staleness for this long after start()


class WatchdogCore:
    """Pure timing logic. `beat(now)` on each control tick; `poll(now)` returns
    a verdict. Latches STALL so it fires once per silent episode."""

    def __init__(self, cfg: WatchdogConfig | None = None):
        self.cfg = cfg or WatchdogConfig()
        self._started: float | None = None
        self._last_beat: float | None = None
        self._beats = 0
        self._last_hb: float = 0.0
        self._hb_beats_at = 0
        self._stalled = False

    def start(self, now: float) -> None:
        self._started = now
        self._last_beat = None
        self._beats = 0
        self._last_hb = now
        self._hb_beats_at = 0
        self._stalled = False

    def beat(self, now: float) -> None:
        self._last_beat = now
        self._beats += 1
        self._stalled = False        # a beat clears the latch

    def poll(self, now: float) -> tuple[WatchVerdict, dict]:
        c = self.cfg
        if self._started is None:
            return WatchVerdict.OK, {}

        ref = self._last_beat if self._last_beat is not None else self._started
        past_grace = now - self._started >= c.startup_grace_s
        if past_grace and not self._stalled and now - ref >= c.stall_after_s:
            self._stalled = True
            return WatchVerdict.STALL, {"silent_s": round(now - ref, 3), "beats": self._beats}

        if now - self._last_hb >= c.heartbeat_every_s:
            span = now - self._last_hb
            hz = round((self._beats - self._hb_beats_at) / span, 1) if span > 0 else 0.0
            self._last_hb = now
            self._hb_beats_at = self._beats
            return WatchVerdict.HEARTBEAT, {"loop_hz": hz, "beats": self._beats,
                                           "stalled": self._stalled}
        return WatchVerdict.OK, {}


class Watchdog:
    def __init__(self, cfg: WatchdogConfig | None = None, *, on_stall=None,
                 sysmon=None, emit=None, clock=time.monotonic, poll_interval_s: float = 0.05):
        self.core = WatchdogCore(cfg)
        self._on_stall = on_stall or (lambda: None)
        self._sysmon = sysmon
        self._emit = emit or (lambda sub, lvl, name, **kv: core.diag.event(sub, lvl, name, **kv))
        self._clock = clock
        self._poll = poll_interval_s
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def beat(self, **_ctx) -> None:
        self.core.beat(self._clock())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.core.start(self._clock())
        self._thread = threading.Thread(target=self._run, name="watchdog", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            verdict, ctx = self.core.poll(self._clock())
            if verdict is WatchVerdict.STALL:
                self._emit("sys", "ERROR", "loop.stall", **ctx)
                try:
                    self._on_stall()
                except Exception as e:                       # noqa: BLE001
                    self._emit("sys", "WARN", "watchdog.on_stall_failed", err=repr(e))
            elif verdict is WatchVerdict.HEARTBEAT:
                self._emit("sys", "INFO", "heartbeat", **ctx)
                if self._sysmon is not None:
                    try:
                        self._sysmon.sample(self._emit)
                    except Exception as e:                   # noqa: BLE001
                        self._emit("sys", "WARN", "sysmon.sample_failed", err=repr(e))
