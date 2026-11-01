"""Memory log (user, 2026-11-01): how much memory the Pi has left, kept after every run so a problem can be looked at afterwards, before the activities move inside the voice service.

A background thread appends one JSON line every `G2_MEMLOG_S` (default 10) seconds to `~/.local/share/g2/memory_log.jsonl` (`G2_MEMLOG` moves it, `G2_MEMLOG=off` turns it off):

  {"t": "...", "kind": "sample", "avail_mb": ..., "used_mb": ..., "swap_used_mb": ..., "g2_rss_mb": all pi_pipeline processes together, "self_rss_mb", "self_peak_mb",
   "threads", "top": [[name, rss_mb] x3, any process], "oom_kills": count since boot, "psi_some_avg10": memory pressure share (the kernel's own number, 0 = none), "load1", "soc_c"}
  {"t": "...", "kind": "note", "label": "goal session start", ...}   what was running (voice service up, a goal session, an attempt, an exploration)
  {"t": "...", "kind": "low", ...}                                    available memory under LOW_AVAIL_MB (once a minute at most), also a diag event "memory.low"

Read it with `python -m pi_pipeline.diag memlog [--hours N]` (`g2mem`): the lowest available memory, the biggest process, swap, memory pressure and any OOM kill, overall and
between notes. Everything degrades to None off Linux (the Mac): nothing is written there. The file is trimmed to its newest half past 8 MB.
"""
from __future__ import annotations

import json
import os
import threading
import time

PATH = "~/.local/share/g2/memory_log.jsonl"
INTERVAL_S = 10.0
LOW_AVAIL_MB = 80.0              # the Pi Zero 2 W has 512 MB in all
MAX_BYTES = 8 * 1024 * 1024
_PROC = "/proc"


def path() -> str:
    return os.path.expanduser(os.environ.get("G2_MEMLOG", PATH))


def enabled() -> bool:
    return os.environ.get("G2_MEMLOG", "").lower() != "off"


def _kb(text: str, key: str) -> float | None:
    for line in text.splitlines():
        if line.startswith(key + ":"):
            try:
                return float(line.split()[1]) / 1024.0
            except (IndexError, ValueError):
                return None
    return None


def _read(p: str) -> str | None:
    try:
        with open(p) as f:
            return f.read()
    except OSError:
        return None


def read_system(proc: str = _PROC) -> dict:
    """Available / used memory and swap in MB from /proc/meminfo; {} when it cannot be read."""
    text = _read(f"{proc}/meminfo")
    if not text:
        return {}
    total, avail = _kb(text, "MemTotal"), _kb(text, "MemAvailable")
    swap_t, swap_f = _kb(text, "SwapTotal"), _kb(text, "SwapFree")
    out = {}
    if total is not None and avail is not None:
        out.update(avail_mb=round(avail, 1), used_mb=round(total - avail, 1), total_mb=round(total, 1))
    if swap_t is not None and swap_f is not None:
        out["swap_used_mb"] = round(swap_t - swap_f, 1)
    return out


def read_processes(proc: str = _PROC, me: int | None = None) -> dict:
    """The resident size of every process (MB), summed for the pi_pipeline ones, this process's own and its peak, the three biggest."""
    me = os.getpid() if me is None else me
    page_mb = (os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096) / (1024.0 * 1024.0)
    rows, g2 = [], 0.0
    try:
        pids = [d for d in os.listdir(proc) if d.isdigit()]
    except OSError:
        return {}
    for pid in pids:
        statm = _read(f"{proc}/{pid}/statm")
        if not statm:
            continue
        try:
            rss = int(statm.split()[1]) * page_mb
        except (IndexError, ValueError):
            continue
        cmd = (_read(f"{proc}/{pid}/cmdline") or "").replace("\0", " ").strip()
        name = (_read(f"{proc}/{pid}/comm") or "?").strip()
        if "pi_pipeline" in cmd:
            g2 += rss
            name = "g2:" + (cmd.split("pi_pipeline", 1)[1].split()[0].strip(".") if "pi_pipeline" in cmd else name)[:24]
        rows.append((name, rss))
    out = {"g2_rss_mb": round(g2, 1), "top": [[n, round(r, 1)] for n, r in sorted(rows, key=lambda x: -x[1])[:3]]}
    status = _read(f"{proc}/{me}/status") or ""
    rss, hwm = _kb(status, "VmRSS"), _kb(status, "VmHWM")
    if rss is not None:
        out["self_rss_mb"] = round(rss, 1)
    if hwm is not None:
        out["self_peak_mb"] = round(hwm, 1)
    for line in status.splitlines():
        if line.startswith("Threads:"):
            try:
                out["threads"] = int(line.split()[1])
            except (IndexError, ValueError):
                pass
    return out


def read_extras(proc: str = _PROC) -> dict:
    out = {}
    vm = _read(f"{proc}/vmstat") or ""
    for line in vm.splitlines():
        if line.startswith("oom_kill "):
            out["oom_kills"] = int(line.split()[1])
    psi = _read(f"{proc}/pressure/memory") or ""
    for line in psi.splitlines():
        if line.startswith("some "):
            for part in line.split():
                if part.startswith("avg10="):
                    out["psi_some_avg10"] = float(part[6:])
    load = _read(f"{proc}/loadavg")
    if load:
        out["load1"] = float(load.split()[0])
    try:
        from .sysmon import read_soc_temp_c
        t = read_soc_temp_c()
        if t is not None:
            out["soc_c"] = round(t, 1)
    except Exception:  # noqa: BLE001
        pass
    return out


def sample(proc: str = _PROC) -> dict:
    """One reading; {} when /proc has nothing (the Mac)."""
    s = read_system(proc)
    if not s:
        return {}
    s.update(read_processes(proc))
    s.update(read_extras(proc))
    return s


def _append(p: str, row: dict) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        if os.path.getsize(p) > MAX_BYTES:                                           # trim to the newest half
            with open(p, "rb") as f:
                f.seek(-MAX_BYTES // 2, os.SEEK_END)
                f.readline()
                keep = f.read()
            with open(p, "wb") as f:
                f.write(keep)
    except OSError:
        pass
    with open(p, "a") as f:
        f.write(json.dumps(row) + "\n")


class MemLog:
    def __init__(self, log_path: str | None = None, interval_s: float | None = None, emit=None, sampler=sample, clock=time.time):
        self.path = log_path or path()
        self.interval_s = interval_s if interval_s is not None else float(os.environ.get("G2_MEMLOG_S", INTERVAL_S))
        self._emit, self._sampler, self._clock = emit, sampler, clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_low = -1e9

    def _now(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._clock()))

    def write(self, kind: str, **fields) -> None:
        try:
            _append(self.path, {"t": self._now(), "kind": kind, **fields})
        except Exception:  # noqa: BLE001 -- a log must never stop what it watches
            pass

    def sample_once(self) -> dict:
        s = self._sampler()
        if not s:
            return {}
        self.write("sample", **s)
        if s.get("avail_mb") is not None and s["avail_mb"] < LOW_AVAIL_MB and self._clock() - self._last_low >= 60.0:
            self._last_low = self._clock()
            self.write("low", **s)
            if self._emit is not None:
                try:
                    self._emit("sys", "WARN", "memory.low", avail_mb=s["avail_mb"], g2_rss_mb=s.get("g2_rss_mb"), top=s.get("top"))
                except Exception:  # noqa: BLE001
                    pass
        return s

    def start(self) -> "MemLog":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="memlog", daemon=True)
            self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(self.interval_s)

    def stop(self) -> None:
        self._stop.set()


_LOG: MemLog | None = None


def start(label: str = "", emit=None) -> MemLog | None:
    """Start the sampler in this process (once) and note the start. No-op when turned off or when this machine has no /proc/meminfo."""
    global _LOG
    if not enabled() or not read_system():
        return None
    if _LOG is None:
        _LOG = MemLog(emit=emit).start()
    if label:
        _LOG.write("note", label=label, pid=os.getpid())
    return _LOG


def note(label: str, **fields) -> None:
    """Note what is happening now ("goal session start", "attempt 3", "exploration end") with a reading beside it. Never raises."""
    if _LOG is None:
        return
    s = _LOG._sampler() or {}
    _LOG.write("note", label=label, pid=os.getpid(), **{k: s[k] for k in ("avail_mb", "g2_rss_mb", "swap_used_mb") if k in s}, **fields)


def read_rows(hours: float | None = None, log_path: str | None = None, now: float | None = None) -> list[dict]:
    p = log_path or path()
    rows = []
    try:
        for ln in open(p):
            try:
                rows.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        return []
    if hours is not None:
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime((now or time.time()) - hours * 3600))
        rows = [r for r in rows if r.get("t", "") >= cutoff]
    return rows


def summarize(rows: list[dict]) -> str:
    """Overall and between notes: the lowest available memory, the biggest total for G2's processes, swap, memory pressure, OOM kills."""
    samples = [r for r in rows if r.get("kind") == "sample"]
    if not samples:
        return "no memory samples in that window"

    def stats(rs):
        lo = min(rs, key=lambda r: r.get("avail_mb", 1e9))
        peak = max(rs, key=lambda r: r.get("g2_rss_mb", 0))
        bits = [f"{len(rs)} samples", f"lowest available {lo['avail_mb']:.0f} MB ({lo['t'][11:]})", f"G2 processes peaked at {peak.get('g2_rss_mb', 0):.0f} MB ({peak['t'][11:]})"]
        if any(r.get("swap_used_mb") for r in rs):
            bits.append(f"swap up to {max(r.get('swap_used_mb', 0) for r in rs):.0f} MB")
        if any(r.get("psi_some_avg10") for r in rs):
            bits.append(f"memory pressure up to {max(r.get('psi_some_avg10', 0) for r in rs):.1f}%")
        kills = [r["oom_kills"] for r in rs if "oom_kills" in r]
        if kills and kills[-1] > kills[0]:
            bits.append(f"OOM KILLS: {kills[-1] - kills[0]}")
        return "; ".join(bits)
    lines = ["overall: " + stats(samples)]
    lows = [r for r in rows if r.get("kind") == "low"]
    if lows:
        lines.append(f"{len(lows)} low-memory warning(s) (under {LOW_AVAIL_MB:.0f} MB available); first at {lows[0]['t']}, biggest then: {lows[0].get('top')}")
    notes = [r for r in rows if r.get("kind") == "note"]
    for i, m in enumerate(notes):
        end = notes[i + 1]["t"] if i + 1 < len(notes) else "9999"
        seg = [r for r in samples if m["t"] <= r["t"] < end]
        if seg:
            lines.append(f"  from {m['t'][5:]} {m.get('label', '')}: " + stats(seg))
    return "\n".join(lines)
