"""The focus lock: while it is held, G2's own initiative stands aside (user, 2026-11-15: "keep the robot focused when we run focused hardware sessions if autonomous behavior is enabled").

One small state file (`~/.local/share/g2/focus.json`, `G2_FOCUS_FILE`) is the single source of truth, so the voice service, an exploration session and a hand-started test, which are separate
processes, agree. Every holder has its own name and an expiry, and the lock is held while ANY holder has not expired: a run holds it for its whole length and refreshes it, a crash lets it
expire by itself within `DEFAULT_TTL_S`, and a person can hold it for a few minutes (`python -m pi_pipeline.focus on 30`).

What it holds back is G2's initiative, by kind: the "Can I go exploring?" ask, the idle sit / rest / sleep descent, the attentive look-around bouts and the idle fidgets. What it never holds back:
a spoken command, the stop words, the emergency stop, the fall and battery guards, and a run that is the holder itself. Every autonomous behavior asks `allow(kind)` (one function); a held
answer is logged at most once a minute per kind, so what would have fired can be read afterwards (`status()` lists the holders and the held-back counts).

    with focus.holding("goal:ball_punt", "goal session"):     # the lock is held (and refreshed) for the whole block
        ...
    if focus.allow("explore_ask"):                              # an autonomous behavior asks first
        ...
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager

log = logging.getLogger("g2.focus")

DEFAULT_PATH = "~/.local/share/g2/focus.json"
DEFAULT_TTL_S = 60.0            # a run's hold: refreshed every REFRESH_S, so a crashed run frees the lock within this long
REFRESH_S = 20.0
MANUAL_DEFAULT_MIN = 30.0       # `focus on` with no minutes
MANUAL_MAX_MIN = 240.0          # a person's hold never lasts longer than this (a forgotten one frees itself)
LOG_EVERY_S = 60.0              # a held-back kind is logged at most this often

KINDS = ("explore_ask", "sleep", "idle", "attentive", "gesture", "chirp")      # what `allow` is asked about (the table in docs/specification/behavior.md)

_lock = threading.Lock()
_last_logged: dict[str, float] = {}


def _path() -> str:
    return os.path.expanduser(os.environ.get("G2_FOCUS_FILE", DEFAULT_PATH))


def _read() -> dict:
    try:
        with open(_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("holders"), dict) else {"holders": {}, "held_back": {}}
    except (OSError, ValueError):
        return {"holders": {}, "held_back": {}}


def _write(d: dict) -> None:
    try:
        p = _path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, p)
    except OSError:
        log.debug("focus lock write failed", exc_info=True)


def _live(d: dict, now: float) -> dict:
    return {k: v for k, v in d.get("holders", {}).items() if isinstance(v, dict) and float(v.get("expires", 0)) > now}


def hold(owner: str, reason: str = "", ttl_s: float = DEFAULT_TTL_S, *, now: float | None = None) -> None:
    """Hold the lock as `owner` for `ttl_s` more seconds (call again to extend)."""
    t = time.time() if now is None else now
    with _lock:
        d = _read()
        if not _live(d, t):
            d["held_back"] = {}                             # a fresh hold starts a fresh count of what was held back
        d["holders"] = _live(d, t)
        prev = d["holders"].get(owner) or {}
        d["holders"][owner] = {"reason": reason or prev.get("reason", ""), "since": prev.get("since", t), "expires": t + float(ttl_s)}
        _write(d)


def release(owner: str | None = None) -> None:
    """Let go of `owner`'s hold (every holder's when `owner` is None)."""
    with _lock:
        d = _read()
        d["holders"] = {} if owner is None else {k: v for k, v in d.get("holders", {}).items() if k != owner}
        _write(d)


def holders(now: float | None = None) -> dict:
    """The live holders: {owner: {reason, since, expires}}."""
    t = time.time() if now is None else now
    return _live(_read(), t)


def held(now: float | None = None) -> bool:
    return bool(holders(now))


def allow(kind: str, *, now: float | None = None) -> bool:
    """May an autonomous behavior of this kind act now? False while any holder has the lock; the held-back event is logged (at most once a minute per kind) and counted."""
    t = time.time() if now is None else now
    live = holders(t)
    if not live:
        return True
    with _lock:
        d = _read()
        d["holders"] = _live(d, t)
        hb = d.setdefault("held_back", {})
        hb[kind] = int(hb.get(kind, 0)) + 1
        _write(d)
        if t - _last_logged.get(kind, -1e9) >= LOG_EVERY_S:
            _last_logged[kind] = t
            log.info("autonomy held back (%s): focus held by %s", kind, ", ".join(f"{k} ({v.get('reason') or '-'})" for k, v in live.items()))
    return False


def status(now: float | None = None) -> dict:
    t = time.time() if now is None else now
    d = _read()
    live = _live(d, t)
    return {"held": bool(live), "holders": {k: {"reason": v.get("reason", ""), "seconds_left": round(float(v["expires"]) - t)} for k, v in live.items()},
            "held_back": dict(d.get("held_back", {}))}


@contextmanager
def holding(owner: str, reason: str = "", ttl_s: float = DEFAULT_TTL_S, refresh_s: float = REFRESH_S):
    """Hold the lock for the block, refreshing it in the background; released at the end however the block ends."""
    stop = threading.Event()
    hold(owner, reason, ttl_s)

    def beat():
        while not stop.wait(refresh_s):
            hold(owner, reason, ttl_s)
    th = threading.Thread(target=beat, name="focus-hold", daemon=True)
    th.start()
    try:
        yield
    finally:
        stop.set()
        release(owner)


def main(argv: list[str] | None = None) -> int:
    """`python -m pi_pipeline.focus on [MINUTES] [REASON...] | off | status`"""
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else "status"
    if cmd == "on":
        minutes = MANUAL_DEFAULT_MIN
        if len(a) > 1:
            try:
                minutes = float(a[1])
            except ValueError:
                print(f"minutes must be a number, not {a[1]!r}")
                return 2
        minutes = max(1.0, min(MANUAL_MAX_MIN, minutes))
        hold("manual", " ".join(a[2:]) or "held by hand", minutes * 60.0)
        print(f"focus held for {minutes:.0f} min: G2 will not ask to explore, settle to rest or sleep, or start look-around bouts")
        return 0
    if cmd == "off":
        release("manual")
        s = status()
        print("focus released" + (f" (still held by {', '.join(s['holders'])})" if s["held"] else ""))
        return 0
    if cmd == "status":
        s = status()
        if not s["held"]:
            print("focus is not held: G2 may act on his own")
        else:
            for k, v in s["holders"].items():
                print(f"held by {k} ({v['reason'] or '-'}), {v['seconds_left'] // 60} min {v['seconds_left'] % 60} s left")
            if s["held_back"]:
                print("held back so far: " + ", ".join(f"{k} x{n}" for k, n in sorted(s["held_back"].items())))
        return 0
    print("usage: python -m pi_pipeline.focus on [MINUTES] [REASON...] | off | status")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
