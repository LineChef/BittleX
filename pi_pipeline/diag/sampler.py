"""Where does the Python time go during a session? A small sampling profiler for the Pi, no downloads.

During exploration 9-23% of the 80 Hz walk ticks run late and speech comes 7-17 s after it is decided (docs/STATUS.md, open problem 6): the walk loop,
the voice loop, the camera reader and the behaviour runtime share one Python process, so they compete for the interpreter. Before moving anything
(a separate walk process, pausing work during walks) this measures which threads actually run Python code and where.

Every `interval_s` a background thread looks at every other thread's current stack (`sys._current_frames()`). On Linux (the Pi) a thread counts as
running when its CPU time (/proc/self/task/<id>/stat) went up since the last sample, and the report also gives each thread's CPU seconds; elsewhere it
falls back to the frame: a thread whose innermost Python frame is a known wait (a queue / lock / event wait, a read) counts as waiting (a C-level
`time.sleep` cannot be seen this way, so off the Pi the shares are rough). The report gives, per thread, the share of samples spent running, and the
functions of G2's own code where it ran most. Cost: one stack walk per thread every 20 ms, a few percent of one
core on the Pi Zero 2 W. Off unless `G2_PROFILE=1` (explore_session starts it); the report is written to the session's diagnostics folder.
"""
from __future__ import annotations

import collections
import os
import sys
import threading
import time
from pathlib import Path

WAIT_FUNCS = frozenset({"sleep", "wait", "_wait", "acquire", "get", "select", "poll", "readline", "read", "recv", "recv_into", "accept",
                        "join", "_wait_for_tstate_lock", "result", "readinto", "in_waiting", "wait_idle"})


def _site(frame) -> str:
    code = frame.f_code
    return f"{Path(code.co_filename).name}:{code.co_name}:{frame.f_lineno}"


def _top_own_frame(frame):
    """The innermost frame that is G2's own code (pi_pipeline/), or the innermost frame if none."""
    f = frame
    while f is not None:
        if "pi_pipeline" in f.f_code.co_filename:
            return f
        f = f.f_back
    return frame


def proc_cpu_ticks(native_id) -> int | None:
    """utime + stime of one thread of this process, in clock ticks (Linux), or None."""
    try:
        with open(f"/proc/self/task/{native_id}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return int(fields[11]) + int(fields[12])           # fields 14 and 15 of stat (utime, stime), counted after the ")" that ends the name
    except (OSError, ValueError, IndexError):
        return None


class Sampler:
    def __init__(self, interval_s: float = 0.02, *, cpu_fn=proc_cpu_ticks):
        self.interval_s = interval_s
        self._cpu_fn = cpu_fn
        self._cpu_last: dict = {}
        self.cpu_ticks = collections.Counter()          # thread name -> CPU ticks seen while sampling (Linux)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples = collections.Counter()           # thread name -> samples
        self.running = collections.Counter()           # thread name -> samples running Python code
        self.where = collections.defaultdict(collections.Counter)    # thread name -> {own-code site: running samples}
        self.started = self.stopped = None

    def start(self) -> "Sampler":
        self.started = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="profiler", daemon=True)
        self._thread.start()
        return self

    def sample_once(self, frames=None, threads=None) -> None:
        frames = sys._current_frames() if frames is None else frames
        threads = {t.ident: t for t in threading.enumerate()} if threads is None else threads
        me = threading.get_ident()
        for ident, frame in frames.items():
            if ident == me:
                continue
            th = threads.get(ident)
            name = th.name if th is not None else f"thread-{ident}"
            self.samples[name] += 1
            ticks = self._cpu_fn(getattr(th, "native_id", None)) if th is not None and self._cpu_fn else None
            if ticks is not None:
                prev = self._cpu_last.get(ident)
                self._cpu_last[ident] = ticks
                if prev is None:
                    continue
                self.cpu_ticks[name] += max(0, ticks - prev)
                if ticks <= prev:
                    continue                              # no CPU time since the last sample: waiting
            elif frame.f_code.co_name in WAIT_FUNCS:
                continue
            self.running[name] += 1
            self.where[name][_site(_top_own_frame(frame))] += 1

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.sample_once()
            except Exception:  # noqa: BLE001 -- profiling must never disturb the session
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1.0)
        self.stopped = time.monotonic()

    def report(self, top: int = 6) -> str:
        secs = (self.stopped or time.monotonic()) - (self.started or time.monotonic())
        lines = [f"sampling profile: {secs:.0f} s, one sample per thread every {self.interval_s * 1000:.0f} ms",
                 "share = samples where the thread was running Python code (not sleeping or waiting on I/O)", ""]
        hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        for name, n in sorted(self.samples.items(), key=lambda kv: -self.running[kv[0]]):
            r = self.running[name]
            cpu = f", CPU {self.cpu_ticks[name] / hz:.1f} s" if self.cpu_ticks else ""
            lines.append(f"{name:24s} running {100.0 * r / max(1, n):5.1f}% of {n} samples{cpu}")
            for site, c in self.where[name].most_common(top):
                lines.append(f"    {100.0 * c / max(1, r):5.1f}%  {site}")
        return "\n".join(lines) + "\n"

    def write(self, folder) -> Path | None:
        try:
            p = Path(folder) / "profile.txt"
            p.write_text(self.report())
            return p
        except OSError:
            return None
