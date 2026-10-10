"""Measuring how long the Pi runs on one charge, as an intentional test, and an optional warning near the end of that runtime.

The Pi's battery (a PiSugar S) can't report its level, so we measure time instead. Nothing here runs unless you start a test:

    python -m pi_pipeline.power runtime test start     # after a FULL charge, before unplugging: starts a heartbeat
    ... let the Pi run until the battery dies ...
    (power it again)  -> the next voice-service start, or `runtime test collect`, records the run

The heartbeat writes the Pi's uptime to a small file every 30 s. After a power loss, the last heartbeat minus the uptime at the start of
the test is how long that charge lasted. If the Pi is instead shut down or rebooted cleanly during a test, the test is discarded (the
battery state afterwards is unknown), so reboots can't be mistaken for an empty battery. `cancel` ends a test by hand.

`RuntimeWatcher` is on by default (G2_PI_BATTERY_WATCH=0 turns it off) but stays silent until a timed test has measured a full runtime.
Then it warns at 80% of that runtime (about 20% left) and again at 95%, counting from boot (a Pi is normally booted on a full battery and then
unplugged). The Pi cannot sense a charger, so you can tell it: "you're plugged in" (or `runtime plugged`) pauses the warning for this boot,
and "you're unplugged" (or `runtime unplugged`) restarts the count from that moment. G2_PI_BATTERY_ARM=manual counts only after "unplugged".
A reboot forgets both."""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from .battery import BatteryLevel

log = logging.getLogger("g2.runtime")

WARN_FRACTION = 0.80       # uptime / full runtime at which "about 20% left" fires
CRITICAL_FRACTION = 0.95
MEASURED = ("test", "log", "confirmed")   # run sources the warning trusts: a timed test, a power loss from power_log.py the user confirmed, or a run the user vouched for as full-to-empty


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

    # -- storage ----------------------------------------------------------
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data, dict):
                data.setdefault("runs", [])
                data.setdefault("test", None)
                return data
        except (OSError, ValueError):
            pass
        return {"test": None, "runs": []}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)           # atomic: a power cut leaves the old file, never half of one

    # -- the intentional test ---------------------------------------------
    def test(self) -> dict | None:
        """The test in progress (or waiting to be collected), or None."""
        return self._load()["test"]

    def arm(self, pid: int | None = None) -> bool:
        """Start a test now. False if one is already running on this boot."""
        data = self._load()
        t = data["test"]
        if t and t.get("boot_id") == self._boot_id():
            return False
        up = self._uptime()
        data["test"] = {"boot_id": self._boot_id(), "start_uptime_s": up, "last_uptime_s": up, "wall": self._wall(),
                        "started": self._wall(), "ended_clean": False, "pid": pid}
        self._save(data)
        return True

    def set_pid(self, pid: int) -> None:
        data = self._load()
        if data["test"]:
            data["test"]["pid"] = pid
            self._save(data)

    def beat(self) -> None:
        data = self._load()
        t = data["test"]
        if t and t.get("boot_id") == self._boot_id():
            t.update(last_uptime_s=self._uptime(), wall=self._wall())
            try:
                self._save(data)
            except OSError:
                log.debug("runtime heartbeat write failed", exc_info=True)

    def run_heartbeat(self) -> None:
        """Beat every `beat_s` until stopped (blocking). On SIGTERM during an OS shutdown the test is flagged clean, i.e. discarded."""
        def _term(*_):
            self._stop.set()
        signal.signal(signal.SIGTERM, _term)
        while not self._stop.is_set():
            self.beat()
            self._stop.wait(self._beat_s)
        if self._shutting_down():
            data = self._load()
            if data["test"] and data["test"].get("boot_id") == self._boot_id():
                data["test"]["ended_clean"] = True
                self._save(data)

    def collect(self) -> str | None:
        """Settle a test left over from a previous boot: a run if the power was lost, nothing if it was shut down cleanly.
        Returns a one-line summary, or None if there was nothing to settle (no test, or one still running on this boot)."""
        data = self._load()
        t = data["test"]
        if not t or t.get("boot_id") == self._boot_id():
            return None
        data["test"] = None
        if t.get("ended_clean"):
            msg = "battery test discarded: the Pi was shut down cleanly, so the battery state afterwards is unknown"
        else:
            runtime = max(0.0, t["last_uptime_s"] - t["start_uptime_s"])
            data["runs"].append({"runtime_s": round(runtime), "ended": t.get("wall"), "source": "test", "counted": True})
            msg = f"battery test recorded: the Pi ran {runtime / 3600:.2f} h on that charge"
        self._save(data)
        log.warning(msg)
        return msg

    def cancel(self) -> bool:
        data = self._load()
        t = data["test"]
        if not t:
            return False
        pid = t.get("pid")
        if pid:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (OSError, ValueError):
                pass
        data["test"] = None
        self._save(data)
        return True

    # -- readouts ---------------------------------------------------------
    def uptime_s(self) -> float:
        return self._uptime()

    # -- "running on battery": the Pi cannot sense a charger, so the person says so ---------------------------------
    def arm_now(self) -> None:
        """"You're unplugged": count battery time from this moment (for this boot)."""
        data = self._load()
        data["armed"] = {"boot_id": self._boot_id(), "uptime_s": self._uptime(), "paused": False}
        self._save(data)

    def disarm(self) -> None:
        """"You're plugged in": pause the warning for this boot."""
        data = self._load()
        data["armed"] = {"boot_id": self._boot_id(), "uptime_s": self._uptime(), "paused": True}
        self._save(data)

    def battery_state(self) -> tuple[str, float | None]:
        """("paused" | "since_unplugged" | "since_boot", seconds counted) for this boot, for display."""
        a = self._load().get("armed")
        if a and a.get("boot_id") == self._boot_id():
            if a.get("paused"):
                return "paused", None
            return "since_unplugged", max(0.0, self._uptime() - a["uptime_s"])
        return "since_boot", self._uptime()

    def armed_elapsed_s(self, from_boot: bool = False) -> float | None:
        """Seconds on battery to count for the warning in THIS boot: since "unplugged" if the person said so; None while paused by
        "plugged in"; and with nothing said, since boot if `from_boot` (else None, meaning not armed)."""
        a = self._load().get("armed")
        if a and a.get("boot_id") == self._boot_id():
            if a.get("paused"):
                return None
            return max(0.0, self._uptime() - a["uptime_s"])
        return self._uptime() if from_boot else None

    def runs(self) -> list[dict]:
        return list(self._load()["runs"])

    def mean_runtime_s(self, sources: tuple | None = None) -> float | None:
        """Mean of the counted runs (only those whose source is in `sources`, if given)."""
        vals = [r["runtime_s"] for r in self.runs()
                if r.get("counted", True) and (sources is None or r.get("source") in sources)]
        return sum(vals) / len(vals) if vals else None

    def add_run(self, runtime_s: float, source: str = "manual", *, ended=None, counted: bool = True) -> None:
        data = self._load()
        data["runs"].append({"runtime_s": round(runtime_s), "ended": ended, "source": source, "counted": counted})
        self._save(data)

    def count_run(self, index: int) -> bool:
        """Confirm a run (e.g. a power loss seen in the power log) as a full charge run to empty, so it enters the estimate."""
        data = self._load()
        if not 0 <= index < len(data["runs"]):
            return False
        data["runs"][index]["counted"] = True
        self._save(data)
        return True

    def forget_run(self, index: int) -> bool:
        data = self._load()
        if not 0 <= index < len(data["runs"]):
            return False
        data["runs"][index]["counted"] = False
        self._save(data)
        return True


class RuntimeWatcher:
    """Checks every `poll_s` how much of the full runtime this boot has used, and calls `on_alert(level, fraction_used)`.
    LOW at 80% used (about 20% battery left), CRITICAL at 95%; repeats every `repeat_s` while it stays that high. Silent until
    a full runtime is known (`full_runtime_s` from settings, else the mean of the recorded runs)."""

    def __init__(self, tracker: RuntimeTracker, on_alert, *, full_runtime_s=None, poll_s: float = 60.0, repeat_s: float = 300.0,
                 clock=time.monotonic, require_arm: bool = False, warn_fraction: float = WARN_FRACTION):
        self._tracker, self._on_alert = tracker, on_alert
        self._warn_fraction = warn_fraction
        self._require_arm = require_arm
        self._override = full_runtime_s or None
        self._poll_s, self._repeat_s, self._clock = poll_s, repeat_s, clock
        self.level = BatteryLevel.OK
        self._last_alert: float | None = None
        self._stop = threading.Event()

    def full_runtime_s(self) -> float | None:
        # only measured runs count (a timed test, or a power loss seen in the power log): a rough manual reading must not trigger siren warnings
        return self._override or self._tracker.mean_runtime_s(sources=MEASURED)

    def poll_once(self) -> BatteryLevel | None:
        full = self.full_runtime_s()
        if not full:
            return None
        elapsed = self._tracker.armed_elapsed_s(from_boot=not self._require_arm)
        if elapsed is None:
            self.level, self._last_alert = BatteryLevel.OK, None
            return None                                     # not told he is on battery (this boot): stay silent
        used = elapsed / full
        seen = BatteryLevel.CRITICAL if used >= CRITICAL_FRACTION else BatteryLevel.LOW if used >= self._warn_fraction else BatteryLevel.OK
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
