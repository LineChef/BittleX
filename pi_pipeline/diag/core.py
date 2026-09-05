"""Diagnostics core: a structured per-session event log + a black-box ring
buffer, so an unknown hardware failure leaves enough context to debug it.

See docs/research/hardware-diagnostics.md.

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
from dataclasses import asdict, is_dataclass
from pathlib import Path

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40, "FATAL": 50, "CRITICAL": 50}

# events at/above this level auto-flush every attached ring buffer
_FLUSH_AT = _LEVELS["ERROR"]
# ... and these event names always flush regardless of their level
_FLUSH_NAMES = {"fall.detected", "loop.stall", "servo.thermal_cooldown", "link.lost"}


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

    def close(self):
        with self._lock:
            if self._fp:
                self.event_locked("sys", "INFO", "session.end")
                self._fp.close()
                self._fp = None

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
        lvl = _LEVELS.get(level.upper(), 20)
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
