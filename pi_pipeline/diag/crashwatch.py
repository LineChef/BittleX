"""Leave enough behind that a crash of the voice service (or an exploration session) can be explained afterwards.

A native crash (segmentation fault in Vosk, PortAudio, onnxruntime...) kills the process with no Python traceback and no chance to log
anything. So while the process runs it keeps three things on disk, and the NEXT start reads them back:

  * a heartbeat file (every `beat_s`, and at every stage change): pid, the stage the loop was in (idle / awake / listening / thinking /
    speaking) and for how long, process memory, free system memory, load, CPU temperature, throttling flags, thread count, the speech
    recogniser's last mic level, and the last log lines;
  * Python's `faulthandler` writing to a file, so a fatal signal leaves the stack of every thread;
  * a "clean" marker written on a normal exit.

At the next start `report_previous()` finds a heartbeat that was never marked clean, logs one WARNING with the stage and the resources at
the time, appends it (with any fault trace) to `crashes.jsonl`, and moves the fault file aside. Read the history with
`python -m pi_pipeline.diag.crashwatch [N]`. Files live in `$G2_CRASH_DIR` (default `~/.local/share/g2/crash`).
"""
from __future__ import annotations

import atexit
import collections
import faulthandler
import json
import logging
import os
import signal
import threading
import time
from pathlib import Path

log = logging.getLogger("g2.crashwatch")

_throttle_cache: list = [-1e9, None]
LOW_MEM_MB = 40.0           # warn (at most every 5 minutes) when the system has less available memory than this


def crash_dir() -> Path:
    return Path(os.environ.get("G2_CRASH_DIR") or Path.home() / ".local/share/g2/crash")


def _meminfo_mb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024.0, 1)
    except Exception:  # noqa: BLE001 -- not Linux
        pass
    return None


def _rss_mb() -> float | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024.0, 1)
    except Exception:  # noqa: BLE001
        pass
    return None


def _snapshot() -> dict:
    snap: dict = {"rss_mb": _rss_mb(), "mem_available_mb": _meminfo_mb(), "threads": threading.active_count()}
    try:
        snap["load1"] = round(os.getloadavg()[0], 2)
    except Exception:  # noqa: BLE001
        pass
    try:
        from .sysmon import read_pi_throttled, read_soc_temp_c
        snap["temp_c"] = read_soc_temp_c()
        now = time.monotonic()
        if now - _throttle_cache[0] > 30.0:                                    # vcgencmd is a process spawn: not on every beat
            th = read_pi_throttled()
            _throttle_cache[:] = [now, th.get("raw") if th else None]
        if _throttle_cache[1]:
            snap["throttled"] = _throttle_cache[1]
    except Exception:  # noqa: BLE001
        pass
    return snap


class _Tail(logging.Handler):
    """Keeps the last few log lines in memory for the heartbeat file."""

    def __init__(self, n: int = 25):
        super().__init__(level=logging.INFO)
        self.lines: collections.deque = collections.deque(maxlen=n)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(f"{time.strftime('%H:%M:%S', time.localtime(record.created))} {record.name} {record.getMessage()}"[:240])
        except Exception:  # noqa: BLE001
            pass


class CrashWatch:
    def __init__(self, name: str = "voice", *, directory: Path | None = None, beat_s: float = 5.0, extras=None, clock=time.time):
        self.name = name
        self.dir = Path(directory) if directory else crash_dir()
        self.beat_s, self._extras, self._clock = beat_s, extras, clock
        self.stage, self.stage_since = "starting", clock()
        self._tail = _Tail()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._fault_fp = None
        self._last_low_mem = 0.0
        self.state_path = self.dir / f"{name}_state.json"
        self.fault_path = self.dir / f"{name}_faults.log"

    # --- reading the previous run ------------------------------------------------------------------------------------------------

    def report_previous(self) -> dict | None:
        """If the previous process of this name ended without marking itself clean, log what it was doing and keep the record."""
        try:
            prev = json.loads(self.state_path.read_text())
        except Exception:  # noqa: BLE001 -- no file: first run
            prev = None
        fault = ""
        try:
            fault = self.fault_path.read_text().strip()
        except Exception:  # noqa: BLE001
            pass
        if prev is None or prev.get("clean") or prev.get("pid") == os.getpid():
            if fault:
                self._keep_fault(fault)
            return None
        rec = {"found_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "name": self.name, "pid": prev.get("pid"), "stage": prev.get("stage"),
               "in_stage_s": prev.get("in_stage_s"), "last_beat": prev.get("time"), "resources": prev.get("resources"),
               "extras": prev.get("extras"), "last_log": prev.get("last_log"), "fault": fault.splitlines()[-40:] if fault else []}
        log.warning("the previous %s process (pid %s) ended without a clean shutdown: last in stage %r for %.0f s, resources %s%s",
                    self.name, rec["pid"], rec["stage"], rec["in_stage_s"] or 0.0, rec["resources"],
                    " -- a fault trace was saved" if fault else " -- no fault trace (killed from outside, or a hard hang)")
        if fault:
            for line in rec["fault"][-15:]:
                log.warning("fault trace: %s", line)
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "crashes.jsonl", "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        if fault:
            self._keep_fault(fault)
        return rec

    def _keep_fault(self, fault: str) -> None:
        try:
            self.fault_path.replace(self.dir / f"{self.name}_faults.{time.strftime('%Y%m%d_%H%M%S')}.log")
        except Exception:  # noqa: BLE001
            pass

    # --- while running ---------------------------------------------------------------------------------------------------------------

    def start(self) -> "CrashWatch":
        self.dir.mkdir(parents=True, exist_ok=True)
        self.report_previous()
        try:
            self._fault_fp = open(self.fault_path, "w")
            faulthandler.enable(file=self._fault_fp, all_threads=True)       # a fatal signal writes every thread's stack here
        except Exception:  # noqa: BLE001
            log.debug("faulthandler to file failed", exc_info=True)
        logging.getLogger().addHandler(self._tail)
        self._write(clean=False)
        threading.Thread(target=self._run, name="crashwatch", daemon=True).start()
        atexit.register(self.stop)
        if threading.current_thread() is threading.main_thread():
            prev = signal.getsignal(signal.SIGTERM)

            def _on_term(sig, frame):                                          # `systemctl stop` / restart is a clean end, not a crash
                self.stop()
                if callable(prev):
                    prev(sig, frame)
                else:
                    raise SystemExit(0)
            try:
                signal.signal(signal.SIGTERM, _on_term)
            except Exception:  # noqa: BLE001
                pass
        return self

    def set_stage(self, stage: str) -> None:
        if stage != self.stage:
            with self._lock:
                self.stage, self.stage_since = stage, self._clock()
            self._write(clean=False)

    def _run(self) -> None:
        while not self._stop.wait(self.beat_s):
            self._write(clean=False)

    def _write(self, *, clean: bool) -> None:
        now = self._clock()
        res = _snapshot()
        extras = None
        if self._extras is not None:
            try:
                extras = self._extras()
            except Exception:  # noqa: BLE001
                extras = None
        state = {"name": self.name, "pid": os.getpid(), "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "clean": clean,
                 "stage": self.stage, "in_stage_s": round(now - self.stage_since, 1), "resources": res, "extras": extras,
                 "last_log": list(self._tail.lines)}
        try:
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, default=str))
            tmp.replace(self.state_path)                                       # atomic: a crash mid-write never leaves half a file
        except Exception:  # noqa: BLE001
            log.debug("heartbeat write failed", exc_info=True)
        mem = res.get("mem_available_mb")
        if mem is not None and mem < LOW_MEM_MB and now - self._last_low_mem > 300:
            self._last_low_mem = now
            log.warning("low memory: %.0f MB available, process using %s MB (stage %s)", mem, res.get("rss_mb"), self.stage)

    def stop(self) -> None:
        """Normal exit: flag the heartbeat clean so the next start does not report a crash."""
        self._stop.set()
        self._write(clean=True)
        try:
            faulthandler.disable()
            if self._fault_fp:
                self._fault_fp.close()
            if self.fault_path.exists() and self.fault_path.stat().st_size == 0:
                self.fault_path.unlink()
        except Exception:  # noqa: BLE001
            pass
        logging.getLogger().removeHandler(self._tail)


class StageTap:
    """Wraps a Cue (voice/cues.py): every stage the loop signals is also recorded as the crash watch's current stage."""

    def __init__(self, inner, watch: CrashWatch):
        self._inner, self._watch = inner, watch

    def set(self, stage) -> None:
        self._watch.set_stage(str(stage))
        self._inner.set(stage)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def history(n: int = 10, directory: Path | None = None) -> list[dict]:
    path = (Path(directory) if directory else crash_dir()) / "crashes.jsonl"
    try:
        rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    except Exception:  # noqa: BLE001
        return []
    return rows[-n:]


def main() -> None:
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    rows = history(n)
    if not rows:
        print("no crashes recorded")
        return
    for r in rows:
        print(f"{r['found_at']}  {r['name']} pid {r['pid']}: stage {r['stage']!r} for {r['in_stage_s']} s; resources {r['resources']}; extras {r['extras']}")
        for line in (r.get("fault") or [])[-8:]:
            print(f"    fault: {line}")
        for line in (r.get("last_log") or [])[-6:]:
            print(f"    log:   {line}")


if __name__ == "__main__":
    main()
