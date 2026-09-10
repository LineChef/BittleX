"""System-health sampling for the watchdog (diagnostics Phase 2).

Battery and Pi-thermal readings. The reader functions degrade to `None` off the
target hardware, so `Sysmon.sample()` is a safe no-op on a dev machine.

  * `read_soc_temp_c()`   -- works on any Linux (incl. the Pi) via
    /sys/class/thermal; None on macOS.
  * `read_pi_throttled()` -- `# HARDWARE`: needs `vcgencmd` (Pi only).
  * `read_battery_v()`    -- `# HARDWARE`: the PiSugar S has NO telemetry; a
    real reading needs an ADC on a BiBoard Grove analog pin (G3/G4). Stub.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

_THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")


def read_soc_temp_c() -> float | None:
    try:
        return int(_THERMAL_ZONE.read_text().strip()) / 1000.0
    except Exception:
        return None


def read_pi_throttled() -> dict | None:
    """`vcgencmd get_throttled` bit flags. Pi-only; None elsewhere."""
    # HARDWARE: vcgencmd ships only on Raspberry Pi OS.
    if not shutil.which("vcgencmd"):
        return None
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                             text=True, timeout=1.0).stdout.strip()
        bits = int(out.split("=")[1], 0)
    except Exception:
        return None
    return {
        "raw": hex(bits),
        "under_voltage_now": bool(bits & 0x1),
        "freq_capped_now": bool(bits & 0x2),
        "throttled_now": bool(bits & 0x4),
        "under_voltage_since_boot": bool(bits & 0x10000),
        "throttled_since_boot": bool(bits & 0x40000),
    }


def read_battery_v() -> float | None:
    # HARDWARE: no source yet. PiSugar S exposes only "external power present";
    # a real pack-voltage reading needs an ADC on a BiBoard Grove pin (G3/G4).
    return None


@dataclass
class SysmonConfig:
    batt_sag_v: float = 6.4          # below this -> battery.sag  (2S LiPo ~6.0 cutoff)
    soc_hot_c: float = 80.0         # above this -> pi.thermal_throttle (soft warn)
    repeat_every_s: float = 30.0    # don't spam the same condition more often than this


class Sysmon:
    """Call `sample(emit)` periodically (the watchdog does, once per heartbeat).
    Emits `battery.sag` / `pi.thermal_throttle` on threshold crossings, rate-
    limited. No-op when every reader returns None."""

    def __init__(self, cfg: SysmonConfig | None = None, *, clock=None):
        self.cfg = cfg or SysmonConfig()
        self._clock = clock or time.monotonic
        self._last_emit: dict[str, float] = {}

    def _should_emit(self, key: str, now: float) -> bool:
        last = self._last_emit.get(key)
        if last is None or now - last >= self.cfg.repeat_every_s:
            self._last_emit[key] = now
            return True
        return False

    def sample(self, emit) -> dict:
        now = self._clock()
        reading: dict = {}
        c = self.cfg

        v = read_battery_v()
        if v is not None:
            reading["battery_v"] = round(v, 2)
            if v <= c.batt_sag_v and self._should_emit("battery.sag", now):
                emit("sys", "ERROR", "battery.sag", voltage=round(v, 2), threshold=c.batt_sag_v)

        thr = read_pi_throttled()
        if thr is not None:
            reading["throttled"] = thr["raw"]
            if (thr["throttled_now"] or thr["under_voltage_now"]) \
                    and self._should_emit("pi.thermal_throttle", now):
                emit("sys", "ERROR", "pi.thermal_throttle", **thr)

        t = read_soc_temp_c()
        if t is not None:
            reading["soc_c"] = round(t, 1)
            if t >= c.soc_hot_c and self._should_emit("pi.thermal_throttle", now):
                emit("sys", "WARN", "pi.thermal_throttle", soc_c=round(t, 1),
                     threshold=c.soc_hot_c)

        return reading
