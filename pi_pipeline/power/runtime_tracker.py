"""How long the Pi runs on one charge, measured automatically, and a warning when the charge is probably about 80% used.

The Pi's battery (a PiSugar S) can't report its level, so we estimate it from time. A heartbeat is written to a small file every
30 s with the Pi's uptime. If the next boot finds that the previous boot never marked a clean shutdown, the Pi lost power: the last
heartbeat's uptime is how long that charge lasted, and it is logged as a run. Averaging the logged runs gives the full runtime;
`RuntimeWatcher` then warns when uptime reaches 80% of it (about 20% battery left) and again near the end.

Assumes each boot starts on a full charge. A hard reset or a pulled plug also looks like "ran out", and a boot on a part-charged
battery gives a short run: use `python -m pi_pipeline.power runtime forget N` to drop a bad one."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from .battery import BatteryLevel

log = logging.getLogger("g2.runtime")

WARN_FRACTION = 0.80       # uptime / full runtime at which "about 20% left" fires
CRITICAL_FRACTION = 0.95


def _read_boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def _read_uptime_s() -> float:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def _system_is_shutting_down() -> bool:
    """True while the OS is powering off or rebooting (not for a plain service restart)."""
    try:
        out = subprocess.run(["systemctl", "is-system-running"], capture_output=True, text=True, timeout=3).stdout.strip()
        return out == "stopping"
    except Exception:  # noqa: BLE001
        return False


class RuntimeTracker:
    def __init__(self, path, *, beat_s: float = 30.0, boot_id=_read_boot_id, uptime=_read_uptime_s,
                 shutting_down=_system_is_shutting_down, wall=time.time):
        self.path = Path(path)
        self._beat_s = beat_s
        self._boot_id, self._uptime, self._shutting_down, self._wall = boot_id, uptime, shutting_down, wall
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- storage ----------------------------------------------------------
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data, dict):
                data.setdefault("runs", [])
                return data
        except (OSError, ValueError):
            pass
        return {"current": None, "runs": []}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)           # atomic: a power cut leaves the old file, never half of one

    # -- the boot bookkeeping ---------------------------------------------
    def start(self) -> "RuntimeTracker":
        with self._lock:
            data = self._load()
            cur, now_boot = data.get("current"), self._boot_id()
            if cur and cur.get("boot_id") != now_boot:       # a previous boot: how did it end?
                if cur.get("clean"):
                    log.info("previous boot ended cleanly (%.1f h up): not a battery run", cur["uptime_s"] / 3600)
                else:
                    run = {"runtime_s": round(cur["uptime_s"]), "ended": cur.get("wall"), "source": "heartbeat", "counted": True}
                    data["runs"].append(run)
                    log.warning("previous boot lost power after %.2f h: logged as a battery run", run["runtime_s"] / 3600)
                cur = None
            if cur is None:
                cur = {"boot_id": now_boot, "uptime_s": self._uptime(), "wall": self._wall(), "clean": False}
            data["current"] = cur
            self._save(data)
        self._thread = threading.Thread(target=self._run, name="runtime-beat", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self._beat_s):
            self.beat()

    def beat(self) -> None:
        with self._lock:
            data = self._load()
            cur = data.get("current") or {"boot_id": self._boot_id()}
            cur.update(uptime_s=self._uptime(), wall=self._wall(), clean=False)
            data["current"] = cur
            try:
                self._save(data)
            except OSError:
                log.debug("runtime heartbeat write failed", exc_info=True)

    def stop(self) -> None:
        """Stop beating. If the OS is shutting down, record this boot as a clean shutdown (not a battery run)."""
        self._stop.set()
        with self._lock:
            data = self._load()
            cur = data.get("current")
            if cur and self._shutting_down():
                cur["clean"] = True
                cur["uptime_s"] = self._uptime()
                try:
                    self._save(data)
                except OSError:
                    log.debug("runtime clean-shutdown write failed", exc_info=True)

    # -- readouts ---------------------------------------------------------
    def uptime_s(self) -> float:
        return self._uptime()

    def runs(self) -> list[dict]:
        return list(self._load()["runs"])

    def mean_runtime_s(self) -> float | None:
        vals = [r["runtime_s"] for r in self.runs() if r.get("counted", True)]
        return sum(vals) / len(vals) if vals else None

    def add_run(self, runtime_s: float, source: str = "manual") -> None:
        with self._lock:
            data = self._load()
            data["runs"].append({"runtime_s": round(runtime_s), "ended": None, "source": source, "counted": True})
            self._save(data)

    def forget_run(self, index: int) -> bool:
        with self._lock:
            data = self._load()
            if not 0 <= index < len(data["runs"]):
                return False
            data["runs"][index]["counted"] = False
            self._save(data)
            return True


class RuntimeWatcher:
    """Checks every `poll_s` how much of the full runtime this boot has used, and calls `on_alert(level, fraction_used)`.
    LOW at 80% used (about 20% battery left), CRITICAL at 95%; repeats every `repeat_s` while it stays that high. Silent until
    a full runtime is known (`full_runtime_s` from settings, else the mean of the logged runs)."""

    def __init__(self, tracker: RuntimeTracker, on_alert, *, full_runtime_s=None, poll_s: float = 60.0, repeat_s: float = 300.0,
                 clock=time.monotonic):
        self._tracker, self._on_alert = tracker, on_alert
        self._override = full_runtime_s or None
        self._poll_s, self._repeat_s, self._clock = poll_s, repeat_s, clock
        self.level = BatteryLevel.OK
        self._last_alert: float | None = None
        self._stop = threading.Event()

    def full_runtime_s(self) -> float | None:
        return self._override or self._tracker.mean_runtime_s()

    def poll_once(self) -> BatteryLevel | None:
        full = self.full_runtime_s()
        if not full:
            return None
        used = self._tracker.uptime_s() / full
        seen = BatteryLevel.CRITICAL if used >= CRITICAL_FRACTION else BatteryLevel.LOW if used >= WARN_FRACTION else BatteryLevel.OK
        now = self._clock()
        if seen == BatteryLevel.OK:
            self.level, self._last_alert = BatteryLevel.OK, None
            return None
        worse = seen > self.level
        self.level = seen
        if worse or self._last_alert is None or now - self._last_alert >= self._repeat_s:
            self._last_alert = now
            log.warning("Pi battery %s: %.0f%% of the expected runtime used", seen.name.lower(), used * 100)
            try:
                self._on_alert(seen, used)
            except Exception:  # noqa: BLE001 -- an alert failing must not stop the watch
                log.debug("pi battery alert handler raised", exc_info=True)
            return seen
        return None

    def start(self) -> "RuntimeWatcher":
        def _run() -> None:
            while not self._stop.wait(self._poll_s):
                self.poll_once()
        threading.Thread(target=_run, name="runtime-watch", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
