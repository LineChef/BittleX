"""Turn the wake word off for a while (user, 2026-11-01): "G2, mic off" (10 minutes) or "G2, mic off for 20 minutes".

While paused, NO wake phrase wakes him ("gee two" and "hey buddy" alike). The microphone stays open for one thing only: the stop words said on their own ("emergency
stop", "freeze", "halt", ...), so a voice stop still works. When the time is up he turns it back on himself and says "Mic back on". To end it early (he cannot hear
"mic on" while paused): `g2mic on` on the Mac, or the review page's Mic button. The end time is kept in a file, so a voice service restart or a deploy keeps the pause.

    python -m pi_pipeline.voice.wake_pause status | on | off [MINUTES]      (g2mic status|on|off)       --json prints one JSON line (the review page)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

log = logging.getLogger("g2.wake_pause")
DEFAULT_MIN = 10
MAX_MIN = 120


def path() -> Path:
    v = os.environ.get("G2_WAKE_PAUSE_FILE", "")
    return Path(v) if v else Path.home() / ".local" / "share" / "g2" / "wake_paused.json"


def _read() -> dict:
    try:
        return json.loads(path().read_text())
    except (OSError, ValueError):
        return {}


def remaining_s(now: float | None = None) -> float:
    """Seconds of the pause left; 0 when the wake word is on."""
    until = _read().get("until")
    if not until:
        return 0.0
    return max(0.0, float(until) - (time.time() if now is None else now))


def is_paused(now: float | None = None) -> bool:
    return remaining_s(now) > 0


def pause(minutes: float | None = None, by: str = "voice", now: float | None = None) -> float:
    """Turn the wake word off for `minutes` (default 10, at most 120). Returns the minutes set."""
    m = max(1.0, min(float(MAX_MIN), float(minutes or DEFAULT_MIN)))
    t = time.time() if now is None else now
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"until": t + m * 60.0, "since": t, "minutes": m, "by": by}))
    log.info("wake word OFF for %.0f min (%s); only the stop words are heard", m, by)
    _event("wake.paused", minutes=m, by=by)
    return m


def resume(by: str = "voice") -> bool:
    """Turn the wake word back on now. Returns whether it was paused."""
    was = is_paused()
    try:
        path().unlink()
    except OSError:
        pass
    if was:
        log.info("wake word back ON early (%s)", by)
        _event("wake.resumed", by=by)
    return was


def status(now: float | None = None) -> dict:
    left = remaining_s(now)
    d = _read()
    out = {"paused": left > 0, "minutes_left": round(left / 60.0, 1)}
    if left > 0:
        out["until"] = time.strftime("%-I:%M %p", time.localtime(float(d["until"])))
        out["by"] = d.get("by")
    return out


def _event(name: str, **kv) -> None:
    try:
        from ..diag import diag
        diag.event("voice", "INFO", name, **kv)
    except Exception:  # noqa: BLE001
        pass


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    cmd = args[0] if args else "status"
    if cmd == "off":
        m = pause(float(args[1]) if len(args) > 1 else None, by="g2mic")
        msg = f"wake word off for {m:.0f} min (only the stop words are heard)"
    elif cmd == "on":
        msg = "wake word back on" if resume(by="g2mic") else "the wake word was already on"
    elif cmd == "status":
        msg = ""
    else:
        print("usage: python -m pi_pipeline.voice.wake_pause status | on | off [MINUTES] [--json]")
        return 2
    s = status()
    if as_json:
        print(json.dumps(s))
    else:
        if msg:
            print(msg)
        print(f"wake word OFF: {s['minutes_left']:.1f} min left (until {s['until']})" if s["paused"] else "wake word ON")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
