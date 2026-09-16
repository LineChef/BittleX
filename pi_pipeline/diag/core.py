"""Diagnostics core: a structured per-session event log + a black-box ring
buffer, so an unknown hardware failure leaves enough context to debug it.

See docs/hardware/diagnostics.md.

    from pi_pipeline.diag import diag, RingBuffer

    diag.start_session("gait", policy_path="gait/run20m_ppo.onnx")
    ring = diag.attach_ring(RingBuffer(seconds=15, hz=80))
    ...
    ring.push(roll=r, pitch=p, jerr=max_err, guard=snap.state)
    diag.event("gait", "WARN", "servo.stall", joint=2, err_deg=24.1)
    # -> events.jsonl line + (WARN>=flush level) blackbox_<ts>.csv dumped

Nothing here needs hardware; it's plain stdlib.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40, "FATAL": 50, "CRITICAL": 50}

# events at/above this level auto-flush every attached ring buffer
_FLUSH_AT = _LEVELS["ERROR"]
# ... and these event names always flush regardless of their level (the failure
# taxonomy incidents from docs/hardware/diagnostics.md)
_FLUSH_NAMES = {
    "fall.detected", "loop.stall", "loop.exception", "unhandled.exception",
    "servo.thermal_cooldown", "servo.stall", "link.lost",
    "imu.stale", "onnx.overrun", "battery.sag", "pi.thermal_throttle",
    "wifi.drop", "cliff.frozen", "jam.detected",
}


def _log_root() -> Path:
    return Path(os.environ.get("G2_LOG_DIR", str(Path.home() / "g2_logs"))).expanduser()


def _git_sha() -> dict:
    try:
        root = Path(__file__).resolve().parents[2]
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                                    capture_output=True, text=True, timeout=3).stdout.strip())
        return {"sha": sha or None, "dirty": dirty}
    except Exception:
        return {"sha": None, "dirty": None}


def _redact(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if any(s in k.lower() for s in ("key", "token", "secret", "password")):
            out[k] = "***"
        elif is_dataclass(v):
            out[k] = _redact(asdict(v))
        elif isinstance(v, dict):
            out[k] = _redact(v)
        else:
            out[k] = v
    return out


def _config_snapshot() -> dict:
    try:
        from pi_pipeline.config import settings
        return _redact(asdict(settings)) if is_dataclass(settings) else {}
    except Exception as e:  # noqa: BLE001
        return {"_error": repr(e)}


def _file_hash(path: str | os.PathLike) -> str | None:
    try:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return None


# --- session query helpers -------------------------------------------------
# Shared by the `python -m pi_pipeline.diag` CLI (prints these) and
# voice/conversation.py's diagnostics_query tool (returns them as text for
# Claude to read and speak from). Nothing here is hardware-specific.

def _sessions() -> list[Path]:
    root = _log_root()
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir() and (p / "events.jsonl").exists()),
                  key=lambda p: p.stat().st_mtime)


def _resolve_session(session: str | None) -> Path | None:
    if not session:
        s = _sessions()
        return s[-1] if s else None
    p = Path(session)
    if p.is_dir():
        return p
    cand = _log_root() / session
    return cand if cand.is_dir() else None


def _read_events(d: Path):
    with open(d / "events.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass


def _thermal_lines(evs: list[dict]) -> list[str]:
    warn = [e for e in evs if e.get("name") == "servo.thermal_warn"]
    soft = [e for e in evs if e.get("name") == "servo.soft_cutback"]
    cool = [e for e in evs if e.get("name") == "servo.thermal_cooldown"]
    rec = [e for e in evs if e.get("name") == "servo.thermal_recover"]
    peak = max((e.get("hottest_frac", 0.0) for e in evs if "hottest_frac" in e), default=0.0)
    if not (warn or soft or cool or peak):
        return ["thermal: nothing logged (guard off, or never warmed)"]
    lines = [f"thermal: peak heat estimate {peak:.0%} of danger line",
             f"WARN x{len(warn)}   soft-cutback x{len(soft)}   COOLDOWN x{len(cool)}   recover x{len(rec)}"]
    joints: dict = {}
    for e in evs:
        j = e.get("hottest_j")
        if j is not None:
            joints[j] = joints.get(j, 0) + 1
    if joints:
        hot = sorted(joints.items(), key=lambda kv: -kv[1])[:3]
        lines.append("hottest joint (ticks): " + ", ".join(f"j{j}:{n}" for j, n in hot))
    for e in cool:
        t = time.strftime("%H:%M:%S", time.localtime(e["wall_ts"]))
        lines.append(f"[{t}] COOLDOWN -- {e.get('reason', '')}")
    return lines


def summarize_session(session: str | None = None) -> str:
    """Plain-text summary of one session's diagnostics: git/host, event-level
    counts, the thermal picture, and the WARN+ timeline. Same content as
    `python -m pi_pipeline.diag summarize`, returned instead of printed --
    this is what the voice diagnostics_query tool speaks from."""
    d = _resolve_session(session)
    if d is None:
        return "No diagnostic sessions found." if not session else f"No session found matching {session!r}."
    evs = list(_read_events(d))
    man = json.loads((d / "manifest.json").read_text()) if (d / "manifest.json").exists() else {}
    lines = [f"session {d.name}"]
    git = man.get("git", {})
    lines.append(f"git {str(git.get('sha'))[:12]}{' (dirty)' if git.get('dirty') else ''}   "
                 f"host {man.get('host')}   argv {' '.join(man.get('argv', [])[:4])}")
    if man.get("policy", {}).get("path"):
        lines.append(f"policy {man['policy']['path']}  sha16 {man['policy'].get('sha256_16')}")
    if not evs:
        lines.append("(no events)")
        return "\n".join(lines)
    dur = evs[-1]["mono_t"] - evs[0]["mono_t"]
    by_lvl: dict = {}
    for e in evs:
        by_lvl[e.get("lvl", "?")] = by_lvl.get(e.get("lvl", "?"), 0) + 1
    lines.append(f"{len(evs)} events over {dur:.0f}s   " + "  ".join(f"{k}:{v}" for k, v in sorted(by_lvl.items())))
    lines.extend(_thermal_lines(evs))
    warn_evs = [e for e in evs if _LEVELS.get(e.get("lvl", "INFO"), 20) >= 30]
    if warn_evs:
        lines.append("timeline (WARN and above):")
        for e in warn_evs:
            t = time.strftime("%H:%M:%S", time.localtime(e["wall_ts"]))
            kv = " ".join(f"{k}={v}" for k, v in e.items()
                          if k not in ("wall_ts", "mono_t", "sid", "sub", "lvl", "name"))
            lines.append(f"[{t}] {e['lvl']:5} {e['sub']}/{e['name']}  {kv}")
    else:
        lines.append("no WARN+ events -- a clean session")
    bb = sorted(d.glob("blackbox_*.csv"))
    if bb:
        lines.append("black-box dumps: " + ", ".join(p.name for p in bb))
    return "\n".join(lines)


def last_failure(session: str | None = None) -> str:
    """The most recent failure-taxonomy event (see `_FLUSH_NAMES`) in a
    session, in plain text -- what the diagnostics_query tool answers
    "why did you fall / stall / lose the link" from."""
    d = _resolve_session(session)
    if d is None:
        return "No diagnostic sessions found." if not session else f"No session found matching {session!r}."
    evs = [e for e in _read_events(d) if e.get("name") in _FLUSH_NAMES
           or _LEVELS.get(e.get("lvl", "INFO"), 20) >= _LEVELS["ERROR"]]
    if not evs:
        return f"No failures logged in session {d.name} -- a clean run."
    e = evs[-1]
    t = time.strftime("%H:%M:%S", time.localtime(e["wall_ts"]))
    kv = " ".join(f"{k}={v}" for k, v in e.items()
                  if k not in ("wall_ts", "mono_t", "sid", "sub", "lvl", "name"))
    return f"[{t}] {e['lvl']} {e['sub']}/{e['name']}  {kv}  (session {d.name})"


class RingBuffer:
    """Fixed-size buffer of recent telemetry rows; dumped on an incident."""

    def __init__(self, seconds: float = 15.0, hz: float = 80.0):
        self.maxlen = max(1, int(seconds * hz))
        self._buf: deque[dict] = deque(maxlen=self.maxlen)
        self._lock = threading.Lock()

    def push(self, **row):
        row.setdefault("mono_t", time.monotonic())
        with self._lock:
            self._buf.append(row)

    def flush(self, path: str | os.PathLike) -> str | None:
        with self._lock:
            rows = list(self._buf)
        if not rows:
            return None
        cols: list[str] = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        path = str(path)
        with open(path, "w") as f:
            f.write(",".join(cols) + "\n")
            for r in rows:
                f.write(",".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + "\n")
        return path


class Diag:
    def __init__(self):
        self._lock = threading.Lock()
        self._fp = None
        self.session_id: str | None = None
        self.session_dir: Path | None = None
        self._rings: list[RingBuffer] = []
        self._incident_n = 0
        self._started_mono: float | None = None
        self._lvl_counts: dict[str, int] = {}
        self._excepthook_installed = False

    # -- lifecycle -----------------------------------------------------------
    def start_session(self, subsystem_hint: str = "run", *,
                      policy_path: str | None = None, extra: dict | None = None) -> str:
        with self._lock:
            if self._fp is not None:
                return self.session_id  # already running
            sid = time.strftime("%Y%m%dT%H%M%S") + f"_{os.getpid() & 0xffff:04x}"
            d = _log_root() / sid
            d.mkdir(parents=True, exist_ok=True)
            self.session_id, self.session_dir = sid, d
            self._fp = open(d / "events.jsonl", "a", buffering=1)
            self._started_mono = time.monotonic()
            self._lvl_counts = {}
            self._incident_n = 0
            manifest = {
                "session_id": sid,
                "started_wall": time.time(),
                "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "subsystem_hint": subsystem_hint,
                "git": _git_sha(),
                "host": socket.gethostname(),
                "pid": os.getpid(),
                "argv": list(__import__("sys").argv),
                "config": _config_snapshot(),
                "policy": {"path": policy_path, "sha256_16": _file_hash(policy_path) if policy_path else None},
                "extra": extra or {},
            }
            (d / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
        self.event(subsystem_hint, "INFO", "session.start", session_id=sid)
        return sid

    def close(self, *, clean: bool = True):
        with self._lock:
            if self._fp:
                self.event_locked("sys", "INFO", "session.end", clean=clean)
                self._fp.close()
                self._fp = None
            self._finalize_manifest(clean)

    def _finalize_manifest(self, clean: bool) -> None:
        """Fill in end-of-session fields so a manifest alone tells you how a run
        went (duration, event counts, incidents, clean vs crash)."""
        if not self.session_dir:
            return
        mpath = self.session_dir / "manifest.json"
        try:
            man = json.loads(mpath.read_text())
        except Exception:
            return
        man["ended_wall"] = time.time()
        man["ended_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if self._started_mono is not None:
            man["duration_s"] = round(time.monotonic() - self._started_mono, 1)
        man["event_counts"] = dict(self._lvl_counts)
        man["incident_count"] = self._incident_n
        man["clean_exit"] = clean
        try:
            mpath.write_text(json.dumps(man, indent=2, default=str))
        except Exception:
            pass

    def incident(self, subsystem: str, name: str, **kv):
        """Log a failure-taxonomy incident at ERROR and guarantee a black-box
        dump -- the explicit 'dump on incident' entry point."""
        self.event(subsystem, "ERROR", name, **kv)

    def install_excepthook(self):
        """Turn an unhandled exception into a FATAL event + black-box flush +
        manifest finalize before the interpreter's own handler runs. Idempotent."""
        if self._excepthook_installed:
            return
        import sys
        prev = sys.excepthook

        def _hook(exc_type, exc, tb):
            try:
                self.event("sys", "FATAL", "unhandled.exception",
                           err=f"{exc_type.__name__}: {exc}")
                self._finalize_manifest(clean=False)
            finally:
                prev(exc_type, exc, tb)

        sys.excepthook = _hook
        self._excepthook_installed = True

    @contextmanager
    def session(self, subsystem_hint: str = "run", **kw):
        """One-line diagnostics for a CLI entrypoint: `start_session` +
        `install_excepthook` + bridge stdlib logging on entry, `close()` on
        exit -- `clean=False` (+ one last FATAL event) if the block raised.

            with diag.session("check_serial", extra={"cmd": args.cmd}):
                ...  # do the thing

        A crash still reaches `sys.excepthook` afterward (this doesn't
        suppress the exception), so the FATAL event and the manifest are
        recorded even if something upstream catches it later.
        """
        self.start_session(subsystem_hint, **kw)
        self.install_excepthook()
        bridge_stdlib_logging()
        try:
            yield self
        except (SystemExit, KeyboardInterrupt):
            # a deliberate exit (sys.exit(N) / Ctrl-C), not a crash -- don't
            # flag it FATAL, but still close so the manifest gets finalized.
            self.close(clean=True)
            raise
        except BaseException as e:
            self.event(subsystem_hint, "FATAL", "session.exception", err=repr(e))
            self.close(clean=False)
            raise
        else:
            self.close(clean=True)

    # -- ring buffers ------------------------------------------------------------
    def attach_ring(self, ring: RingBuffer) -> RingBuffer:
        self._rings.append(ring)
        return ring

    def _dump_rings(self, why: str):
        if not (self._rings and self.session_dir):
            return
        self._incident_n += 1
        ts = time.strftime("%H%M%S")
        for i, ring in enumerate(self._rings):
            suffix = f"_{i}" if len(self._rings) > 1 else ""
            ring.flush(self.session_dir / f"blackbox_{ts}_{self._incident_n:02d}{suffix}.csv")

    # -- events ---------------------------------------------------------------
    def event(self, subsystem: str, level: str, name: str, **kv):
        with self._lock:
            self.event_locked(subsystem, level, name, **kv)

    def event_locked(self, subsystem: str, level: str, name: str, **kv):
        if self._fp is None:            # lazily auto-start so nothing is lost
            self._lock.release()
            try:
                self.start_session("auto")
            finally:
                self._lock.acquire()
        rec = {"wall_ts": round(time.time(), 3), "mono_t": round(time.monotonic(), 4),
               "sid": self.session_id, "sub": subsystem, "lvl": level.upper(), "name": name}
        rec.update(kv)
        try:
            self._fp.write(json.dumps(rec, default=str) + "\n")
        except Exception:
            pass
        lu = level.upper()
        self._lvl_counts[lu] = self._lvl_counts.get(lu, 0) + 1
        lvl = _LEVELS.get(lu, 20)
        if lvl >= _FLUSH_AT or name in _FLUSH_NAMES:
            self._dump_rings(name)


diag = Diag()


class DiagLogHandler(logging.Handler):
    """Mirror every stdlib `g2.*` log record into the diag event stream."""

    def emit(self, record: logging.LogRecord):
        try:
            diag.event(record.name, record.levelname, "log", msg=record.getMessage())
        except Exception:
            pass


def bridge_stdlib_logging(root: str = "g2"):
    lg = logging.getLogger(root)
    if not any(isinstance(h, DiagLogHandler) for h in lg.handlers):
        lg.addHandler(DiagLogHandler())
    lg.setLevel(min(lg.level or logging.INFO, logging.INFO))
