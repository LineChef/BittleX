"""Always-on power diary of the voice service (user, 2026-10-10: "add a log for when we enter and leave sleep mode", "use this for the
runtime estimate on the pi").

One JSON line per event, each flushed to the SD card at once (the journal on the Pi is lost with the power):

    start / stop    the voice service started / stopped (`shutdown: true` when the OS was powering off or rebooting)
    sleep / wake    G2 went to sleep after a long rest / woke up (with the reason)
    alive           a heartbeat every minute, awake or asleep (`asleep: true|false`)
    runtime         written at the next start, when the previous boot ended without a stop: the Pi lost power

So after the Pi goes quiet, the last line says whether G2 was asleep or awake and when he was last alive. A power loss is
written to the runtime records (`runtime_tracker.py`, source "log") as an UNCOUNTED candidate: the Pi cannot know it was booted on a full
charge or that nobody plugged it in on the way, and a run cut short would pull the estimate down (user, 2026-10-10: the Pi is not always run
until the battery is dead). It enters the estimate only when the user confirms it was a full charge run to empty:
`python -m pi_pipeline.power runtime count <index>`.

    ~/.local/share/g2/power_log.jsonl      (G2_POWER_LOG)
    python -m pi_pipeline.power log [N]     # the last N lines in local time
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from .runtime_tracker import _read_boot_id, _read_uptime_s, _system_is_shutting_down

log = logging.getLogger("g2.powerlog")

DEFAULT_PATH = "~/.local/share/g2/power_log.jsonl"


class PowerLog:
    def __init__(self, path=None, *, boot_id=_read_boot_id, uptime=_read_uptime_s, wall=time.time,
                 shutting_down=_system_is_shutting_down, max_lines: int = 5000):
        self.path = Path(os.path.expanduser(path or os.environ.get("G2_POWER_LOG", DEFAULT_PATH)))
        self._boot_id, self._uptime, self._wall, self._shutting_down = boot_id, uptime, wall, shutting_down
        self._max_lines = max_lines
        self.asleep = False
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # -- writing ----------------------------------------------------------
    def event(self, kind: str, **fields) -> None:
        """Append one line and fsync it; never raises (the log must not take the voice service down)."""
        if kind == "sleep":
            self.asleep = True
        elif kind == "wake":
            self.asleep = False
        line = {"t": round(self._wall(), 1), "boot": self._boot_id(), "up": round(self._uptime(), 1), "event": kind, **fields}
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "ab+") as f:
                    f.seek(0, os.SEEK_END)
                    lead = b""
                    if f.tell():
                        f.seek(-1, os.SEEK_END)
                        lead = b"" if f.read(1) == b"\n" else b"\n"   # a line cut by a power loss: start on a fresh line
                    f.write(lead + (json.dumps(line) + "\n").encode())
                    f.flush()
                    os.fsync(f.fileno())
        except OSError:
            log.debug("power log write failed", exc_info=True)

    def heartbeat(self) -> None:
        self.event("alive", asleep=self.asleep)

    def start(self, every_s: float = 60.0) -> "PowerLog":
        """Trim, write `start`, then a heartbeat every `every_s` on a daemon thread."""
        self._trim()
        self.event("start")

        def _run():
            while not self._stop.wait(every_s):
                self.heartbeat()
        threading.Thread(target=_run, name="power-log", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self.event("stop", shutdown=bool(self._shutting_down()), asleep=self.asleep)

    def _trim(self) -> None:
        lines = self._raw_lines()
        if len(lines) > self._max_lines:
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text("".join(lines[-self._max_lines:]))
                os.replace(tmp, self.path)
            except OSError:
                log.debug("power log trim failed", exc_info=True)

    # -- reading ----------------------------------------------------------
    def _raw_lines(self) -> list[str]:
        try:
            with open(self.path) as f:
                return f.readlines()
        except OSError:
            return []

    def lines(self) -> list[dict]:
        out = []
        for s in self._raw_lines():
            try:
                out.append(json.loads(s))
            except ValueError:
                continue                                  # a line cut by the power loss
        return out

    def collect_into(self, tracker, *, record: bool = True) -> str | None:
        """Settle the previous boot once: a power loss is added to `tracker` as an uncounted run (source "log"); `record=False` only marks it settled
        (an intentional battery test already recorded that boot). Returns a one-line summary or None."""
        rows = self.lines()
        me = self._boot_id()
        prev = [r for r in rows if r.get("boot") and r.get("boot") != me]
        if not prev:
            return None
        last_boot = prev[-1]["boot"]
        if any(r.get("event") == "runtime" and r.get("of_boot") == last_boot for r in rows):
            return None                                   # already settled
        last = [r for r in prev if r["boot"] == last_boot][-1]
        state = "asleep" if last.get("asleep") or (last.get("event") == "sleep") else "awake"
        if last.get("event") == "stop" and last.get("shutdown"):
            outcome, counted = "clean shutdown", None
        elif last.get("event") == "stop":
            outcome, counted = "service stopped before the end (lower bound)", False
        else:
            outcome, counted = "power lost, not counted until you confirm a full charge (runtime count <index>)", False
        runtime = float(last.get("up", 0.0))
        if not record:
            outcome, counted = "recorded by the battery test", None
        if counted is not None:
            tracker.add_run(runtime, source="log", ended=last.get("t"), counted=counted)
        self.event("runtime", of_boot=last_boot, runtime_s=round(runtime), outcome=outcome, last_state=state, counted=False)
        msg = f"previous boot: {outcome} after {runtime / 3600:.2f} h, last seen {state}"
        log.warning(msg)
        return msg


def format_line(r: dict) -> str:
    t = time.strftime("%Y-%m-%d %I:%M:%S %p", time.localtime(r.get("t", 0)))
    extra = " ".join(f"{k}={v}" for k, v in r.items() if k not in ("t", "boot", "up", "event"))
    return f"{t}  up {float(r.get('up', 0)) / 3600:5.2f} h  {r.get('event', '?'):8s} {extra}".rstrip()
